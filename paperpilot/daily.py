"""Personalized research news, selected from public publisher pages."""
import html
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET
from . import discovery as d, store, news_sources

LOCK = threading.Lock()
TTL = 3600
WINDOW_HOURS = 72
OUTLETS = tuple(source for group in d.NEWS_GROUPS.values() for source in group)
DAILY_ARTICLE_LIMIT = 12
SOURCE_VERSION = 5
LOCAL_ZONE = timezone(timedelta(hours=8))
FEED_BASE = 'https://raw.githubusercontent.com/osnsyc/Wechat-Scholar/main/channels/'
# Verified against the publisher names in Wechat-Scholar/channels.json.
WECHAT_FEEDS = {
    'qbitai': ('gh_114e76fd6e5d', 'MzIzNjc1NzUzMw=='),
    'aiera': ('gh_108f2a2a27f4', 'MzI3MTA0MTk1MA=='),
    'jiqizhixin': ('gh_dbc0a5474692', 'MzA3MzI4MjgzMw=='),
    'leaderobot': ('gh_5b0b6bcc7a39', 'MzI5MzE0NDUzNQ=='),
    'deeptech': ('gh_27c43c799b0c', None),
    'aitechreview': ('gh_6ca2fbc2df6e', 'MzA5ODEzMjIyMA=='),
}
# Public OPML source: https://gist.github.com/discountry/80a05b0123f340014f98b6099a3ae5ab
# Every fetch must match the RSS publisher title; endpoints may be unavailable or delayed.
EXTRA_WECHAT_FEEDS = {
    'jazzyear': 'https://wechat2rss.bestblogs.dev/feed/1c4008936645d5c17239d99bba91522cf2bdfa26.xml',
    'zpotentials': 'https://wechat2rss.bestblogs.dev/feed/c47f4bc00ea912c37b6e23b22b146db0e85b3e19.xml',
}
WECHAT_BODY_LOCK = threading.Lock()


def enabled():
    return store.settings().get('hotspot_news_enabled', True)


def require_enabled():
    if not enabled():
        raise ValueError('领域动态已关闭，可在模型设置中重新开启')


def disabled_result():
    return {'items': [], 'articles': [], 'source_status': [], 'updated_at': None,
            'stale': False, 'enabled': False}


def utcnow():
    return datetime.now(timezone.utc)


def stamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return result if result.tzinfo else None
    except (ValueError, TypeError, AttributeError):
        return None


def window_start(now):
    return now.astimezone(LOCAL_ZONE).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=2)


def recent(value, now):
    t = stamp(value)
    return bool(t and window_start(now) <= t <= now)


def limit_articles(articles, limit=DAILY_ARTICLE_LIMIT):
    """Rank and deduplicate across sources, optionally cap each publication day."""
    def score(row):
        value = row.get('selection_score', 0)
        return value if type(value) in (int, float) and 0 <= value <= 100 else 0
    ordered = sorted((a for a in articles if stamp(a.get('published'))),
                     key=lambda a: (-score(a), -stamp(a['published']).timestamp(), a['source_url']))
    days, seen, output = {}, set(), []
    for article in ordered:
        day = stamp(article['published']).astimezone(LOCAL_ZONE).date()
        # Deduplicate syndicated titles as well as identical URLs, including cache merges.
        title = re.sub(r'\W+', '', article.get('title', '')).casefold()
        identity = (day, title or article['source_url'])
        if identity in seen or article['source_url'] in seen or (limit is not None and days.get(day, 0) >= limit):
            continue
        seen.update((identity, article['source_url']))
        days[day] = days.get(day, 0) + 1
        output.append(article)
    return sorted(output, key=lambda a: stamp(a['published']), reverse=True)


def limit_edition(value):
    pool = value.get('article_pool', value.get('articles', []))
    articles = limit_articles(pool)
    urls = {a['source_url'] for a in articles}
    extra = set(value.get('extra_urls', []))
    articles += [a for a in pool if a['source_url'] in extra and a['source_url'] not in urls]
    urls = {a['source_url'] for a in articles}
    items = [{**p, 'reports': [r for r in p['reports'] if r['source_url'] in urls]}
             for p in value.get('paper_pool', value.get('items', []))]
    return {**value, 'articles': articles, 'items': [p for p in items if p['reports']],
            'extra_urls': [url for url in value.get('extra_urls', []) if url in urls],
            'daily_article_limit': DAILY_ARTICLE_LIMIT}


def for_day(value, offset=0, now=None):
    if type(offset) is not int or offset not in (0, 1, 2):
        raise ValueError('请选择今日、昨日或前日')
    now = now or utcnow()
    target = (now.astimezone(LOCAL_ZONE).date() - timedelta(days=offset)).isoformat()
    def matches(row):
        t = stamp(row.get('published'))
        return bool(t and t <= now and t.astimezone(LOCAL_ZONE).date().isoformat() == target)
    value = limit_edition({**value, 'articles': [a for a in value.get('articles', []) if matches(a)],
                           **({'article_pool': [a for a in value['article_pool'] if matches(a)]} if 'article_pool' in value else {})})
    from . import hotspot_triage
    skipped = {r['identity'] for r in hotspot_triage.public()}
    shown = {a['source_url'] for a in value['articles']}
    remaining = [a for a in value.get('article_pool', []) if matches(a) and a['source_url'] not in shown
                 and hotspot_triage.identity(a, 'article') not in skipped]
    items = [{**p, 'reports': [r for r in p['reports'] if matches(r)]} for p in value['items']]
    return {**{k:v for k,v in value.items() if k not in ('article_pool', 'paper_pool')},
            'has_more': bool(remaining), 'day': offset, 'date': target,
            'articles': sorted((a for a in value.get('articles', []) if matches(a)),
                               key=lambda a: (a['source_url'] in value.get('extra_urls', []),
                                              value.get('extra_urls', []).index(a['source_url']) if a['source_url'] in value.get('extra_urls', []) else -stamp(a['published']).timestamp())),
            'items': sorted((p for p in items if p['reports']),
                            key=lambda p: max(stamp(r['published']) for r in p['reports']), reverse=True)}


def more(offset, expected_count, expected_date):
    """Expose four additional model-approved articles; never rerun the model here."""
    from . import hotspot_triage, daily_filter, news_metadata
    require_enabled()
    if type(expected_count) is not int or expected_count < 0:
        raise ValueError('列表状态无效，请刷新后重试')
    with LOCK:
        value = cached()
        current = for_day(value, offset)
        if current['date'] != expected_date:
            raise ValueError('日期已变化，请刷新动态后重试')
        # Make retries and concurrent clicks from old tabs idempotent.
        if len(current['articles']) != expected_count:
            return current
        signature = daily_filter.context_signature()[0]
        if (value.get('filtering', {}).get('context_signature') != signature or
                value.get('sources_signature') != news_sources.signature()):
            raise ValueError('研究档案或关注来源已变化，请先刷新动态')
        shown = {a['source_url'] for a in value['articles']}
        skipped = {r['identity'] for r in hotspot_triage.public()}
        candidates = [a for a in value.get('article_pool', [])
                      if a['source_url'] not in shown
                      and stamp(a['published']).astimezone(LOCAL_ZONE).date().isoformat() == current['date']
                      and hotspot_triage.identity(a, 'article') not in skipped]
        candidates.sort(key=lambda a: (-a.get('selection_score', 0), -stamp(a['published']).timestamp(), a['source_url']))
        extra = candidates[:4]
        if not extra:
            return current
        result = limit_edition({**value, 'extra_urls': value.get('extra_urls', []) + [a['source_url'] for a in extra]})
        urls = {a['source_url'] for a in extra}
        added_papers = [p for p in result['items'] if any(r['source_url'] in urls for r in p['reports'])]
        repaired = {p['id']:p for p in news_metadata.enrich(added_papers, check=require_enabled)}
        result['paper_pool'] = [{**p, **{k:v for k,v in repaired.get(p['id'], {}).items() if k != 'reports'}}
                                for p in result.get('paper_pool', result['items'])]
        require_enabled()
        if daily_filter.context_signature()[0] != signature or news_sources.signature() != value.get('sources_signature'):
            raise ValueError('筛选依据已变化，请刷新动态后重试')
        store.save('daily', limit_edition(result))
        return for_day(cached(), offset)


class Body(HTMLParser):
    """Only read article content, excluding menus, related articles and scripts."""
    def __init__(self, marker):
        super().__init__(); self.marker = marker; self.stack = []; self.parts = []; self.skip = 0; self.found = False
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if not self.stack and (a.get('id') == self.marker or self.marker in a.get('class', '').split()):
            self.stack = [tag]; self.found = True; return
        if not self.stack:
            return
        if tag not in ('br', 'img', 'hr', 'input', 'meta', 'link', 'source', 'wbr', 'area', 'embed'):
            self.stack.append(tag)
        if tag in ('script', 'style'):
            self.skip += 1
        if tag == 'a' and not self.skip:
            self.parts.append(' ' + a.get('href', '') + ' ')
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.skip = max(0, self.skip - 1)
        if tag in self.stack:
            while self.stack:
                if self.stack.pop() == tag:
                    break
        if tag in ('p', 'div', 'br'):
            self.parts.append('\n')
    def handle_data(self, value):
        if self.stack and not self.skip:
            self.parts.append(value)


def article_body(raw, source):
    parser = Body('js_content')
    parser.feed(raw)
    if not parser.found:
        raise ValueError('正文格式变化，未能提取论文链接')
    return ''.join(parser.parts)


def paper_links(text):
    """Only verified URL shapes, never infer a paper from a headline."""
    text = html.unescape(text)
    # Repair DOI suffixes broken by layout whitespace, not ordinary following prose.
    text = re.sub(r'(https?://doi\.org/10\.\d{4,9}/[^\s<>"，。；）\]]+)\s+(?=\d+(?:\.[A-Za-z0-9_-]+){2,}(?:[\s<>"，。；）\]]|$))', r'\1', text)
    links = {}
    for match in re.finditer(r'(?:https?://)?(?:www\.)?arxiv\.org/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)', text):
        ident = re.sub(r'v\d+$', '', match[1])
        links[ident] = 'https://arxiv.org/abs/' + ident
    for url in re.findall(r'https?://(?:doi\.org/10\.\d{4,9}/[^\s<>"，。；）\]]+|openreview\.net/(?:forum|pdf)\?id=[\w-]+)', text):
        url = url.rstrip(').,;').replace('http://', 'https://').replace('openreview.net/pdf?', 'openreview.net/forum?')
        links[url] = url
    return links


def wechat_url(value, source=None):
    """Accept only public WeChat article URLs, not redirects or other publishers."""
    try:
        p = urlparse(html.unescape(value.strip()))
        if (p.scheme not in ('http', 'https') or p.hostname != 'mp.weixin.qq.com'
                or p.port not in (None, 443) or p.username or p.password):
            return ''
        if p.path == '/s':
            query = parse_qs(p.query)
            if not all(query.get(k) for k in ('__biz', 'mid', 'idx', 'sn')):
                return ''
            if source in WECHAT_FEEDS and WECHAT_FEEDS[source][1] and query['__biz'] != [WECHAT_FEEDS[source][1]]:
                return ''
            # Tracking parameters do not identify a different article.
            query = urlencode({k: query[k][0] for k in ('__biz', 'mid', 'idx', 'sn')})
            return urlunparse(('https', 'mp.weixin.qq.com', '/s', '', query, ''))
        if re.fullmatch(r'/s/[A-Za-z0-9_-]+', p.path):
            return urlunparse(('https', 'mp.weixin.qq.com', p.path, '', '', ''))
    except (AttributeError, TypeError, ValueError):
        pass
    return ''


def is_wechat_article(row):
    return row.get('channel') == 'wechat' and bool(wechat_url(row.get('source_url'), row.get('source')))


def wechat_articles(source, now):
    if source not in WECHAT_FEEDS and source not in EXTRA_WECHAT_FEEDS:
        raise ValueError('暂未接入可核实的微信推送源，已停用官网替代')
    feed_url = EXTRA_WECHAT_FEEDS[source] if source in EXTRA_WECHAT_FEEDS else FEED_BASE + WECHAT_FEEDS[source][0] + '.xml'
    raw = d.public_fetch(feed_url, {urlparse(feed_url).hostname})
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('公众号订阅源暂不可读') from None
    if root.tag != 'rss' or root.findtext('./channel/title') != d.SOURCES[source]['name']:
        raise ValueError('订阅源公众号身份不匹配，未纳入动态')
    rows, seen, dates, invalid = [], set(), [], 0
    for item in root.findall('./channel/item'):
        url = wechat_url(item.findtext('link'), source)
        title = d.clean_text(item.findtext('title') or '')
        try:
            published = parsedate_to_datetime(item.findtext('pubDate') or '')
        except (TypeError, ValueError, OverflowError):
            published = None
        if not url or not title or not published or not published.tzinfo:
            invalid += 1
            continue
        dates.append(published)
        if url in seen or not recent(published.isoformat(), now):
            continue
        seen.add(url)
        row = {'title': title, 'source_url': url, 'source': source, 'published': published.isoformat(),
               'channel': 'wechat', 'feed_url': feed_url, 'date_inferred': False,
               'excerpt': item.findtext('description') or ''}
        content = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded')
        if content and content.strip():
            row['body'] = article_body('<div id="js_content">' + content + '</div>', source)
        rows.append(row)
    latest = max(dates).astimezone(LOCAL_ZONE).strftime('%m-%d %H:%M') if dates else '未知'
    provider = 'BestBlogs' if source in EXTRA_WECHAT_FEEDS else 'Wechat-Scholar'
    coverage = f'微信公众号 RSS（{provider}），源内最新推送 {latest}；第三方定时更新，可能延迟或遗漏'
    if invalid:
        coverage += f'；{invalid} 条地址或时间不可核实，已跳过'
    if dates and min(dates) > window_start(now):
        coverage += '；当前订阅未覆盖完整三日'
    return rows, coverage


def read_wechat_article(row, now, blocked=None):
    if not is_wechat_article(row):
        raise ValueError('仅接收微信公众号原文')
    if 'body' in row:
        return row, paper_links(row['body'])
    try:
        # A challenge stops further WeChat requests in this refresh. Never retry it.
        with WECHAT_BODY_LOCK:
            if blocked is not None and blocked.is_set():
                raise ValueError('微信正文暂不可读')
            raw = d.public_fetch(row['source_url'], {'mp.weixin.qq.com'})
            if any(x in raw for x in ('环境异常', '访问过于频繁', '请完成验证')) and 'id="js_content"' not in raw:
                if blocked is not None:
                    blocked.set()
                raise ValueError('微信正文需浏览器验证')
        body = article_body(raw, row['source'])
        if not body.strip():
            raise ValueError('微信正文为空')
        return {**row, 'body': body}, paper_links(body)
    except Exception:
        # RSS titles remain useful when WeChat blocks full text. Excerpts are not full text.
        excerpt = article_body('<div id="js_content">' + row.get('excerpt', '') + '</div>', row['source'])
        return {**row, 'links_unavailable': True}, paper_links(excerpt)


def is_article(row):
    if row.get('channel') == 'rss':
        return any(r['id'] == row.get('source') and r['url'] == row.get('feed_url') for r in news_sources.current()['custom'])
    if is_wechat_article(row):
        return True
    source = row.get('source')
    if row.get('channel') != 'website' or source not in d.SOURCES:
        return False
    try:
        p=urlparse(row.get('source_url', ''))
        host=urlparse(d.SOURCES[source]['url']).hostname
        return p.scheme == 'https' and p.hostname in {host, host.removeprefix('www.')} and not p.username and not p.password and p.port in (None,443)
    except ValueError:
        return False


def articles(source, now):
    from .daily_sources import website_articles
    if source in EXTRA_WECHAT_FEEDS:
        return wechat_articles(source, now)
    try:
        rows, coverage=website_articles(source, now)
        if rows or source not in WECHAT_FEEDS:
            return [{**r, 'channel':'website'} for r in rows], coverage
        rows, fallback=wechat_articles(source, now)
        return rows, '官网近三日无可读文章，使用微信 RSS 补充；'+fallback
    except Exception:
        if source not in WECHAT_FEEDS:
            raise
        rows, coverage=wechat_articles(source, now)
        return rows, '官网暂不可读，使用微信 RSS 补充；'+coverage


def read_article(row, now, blocked=None):
    from .daily_sources import read_website_article
    if row.get('channel') == 'rss':
        return {**row, 'body': d.clean_text(row.get('body', ''))}, paper_links(row.get('body', ''))
    if is_wechat_article(row):
        return read_wechat_article(row, now, blocked)
    if not is_article(row):
        raise ValueError('来源地址无效')
    updated, links=read_website_article(row,now)
    return {**updated,'channel':'website'},links


def metadata(ids):
    if not ids:
        return {}
    output = {}
    # One API call per batch, with the same global arXiv rate limit as search.
    for start in range(0, len(ids), 50):
        with d.LOCK:
            time.sleep(max(0, 3 - (time.monotonic() - d.LAST_REQUEST)))
            try:
                raw = d.public_fetch('https://export.arxiv.org/api/query?' + urlencode({'id_list': ','.join(ids[start:start+50]), 'max_results': 50}), {'export.arxiv.org', 'arxiv.org'})
            finally:
                d.LAST_REQUEST = time.monotonic()
        ns = {'a': 'http://www.w3.org/2005/Atom'}
        for entry in ET.fromstring(raw).findall('a:entry', ns):
            value = lambda k: ' '.join(entry.findtext('a:' + k, '', ns).split())
            try:
                ident = re.sub(r'v\d+$', '', d.arxiv_id(value('id').replace('http://', 'https://')))
            except ValueError:
                continue
            output[ident] = {'title': value('title'), 'abstract': value('summary'), 'published': value('published'),
                             'authors': [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)]}
    return output


def collect(now=None):
    require_enabled()
    now = now or utcnow()
    sources = news_sources.current()
    custom = {r['id']: r for r in sources['custom']}
    source_catalog = news_sources.catalog(sources)
    papers, statuses, reports_by_url = {}, [], {}
    blocked = threading.Event()
    from . import web_supplement, news_cache
    from .daily_sources import SINCE
    evidence = news_cache.Cache(sources, now)
    web_enabled = web_supplement.enabled()
    def listing(source):
        token = SINCE.set(evidence.since(source))
        try:
            return news_sources.articles(custom[source], now) if source in custom else articles(source, now)
        finally:
            SINCE.reset(token)
    web = web_supplement.Session(searches=0, fetches=6)
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = {s: pool.submit(listing, s) for s in sources['selected']}
        for source, task in tasks.items():
            require_enabled()
            listing_failed = False
            try:
                rows, coverage = task.result()
            except Exception as e:
                listing_failed = True
                coverage = str(e)[:180] if isinstance(e, ValueError) else '公开入口暂不可读，请稍后重试'
                rows = evidence.listings.get(source, {}).get('rows', [])
                if not rows:
                    statuses.append({'source': source, 'ok': False, 'count': 0, 'message': coverage})
                    continue
                coverage += '；复用本地近三日缓存'
            else:
                rows = evidence.merge(source, rows)
            failures, found = 0, set()
            details = []
            for original in rows:
                cached_body = evidence.body(original, web_enabled)
                details.append((original, cached_body, None if cached_body else pool.submit(read_article, original, now, blocked)))
            for original, cached_body, detail in details:
                try:
                    row, links = cached_body if cached_body else detail.result()
                except Exception:
                    if source == 'embodied' and original.get('channel') == 'website':
                        continue  # Its listing date can be an edit date; require the original body timestamp.
                    row, links = original, {}
                    row = {**row, 'links_unavailable': True}
                if not recent(row.get('published'), now):
                    continue
                if not is_article(row):
                    continue
                if not cached_body and web_enabled and (row.get('links_unavailable') or len(row.get('body', '').strip()) < 200):
                    # Run in caller scope: background page readers must never access another account's key/cache.
                    supplemented = web_supplement.supplement_article(row, web)
                    if supplemented:
                        row, links = supplemented
                if not cached_body:
                    evidence.remember(original, row, links, web_enabled)
                if row.get('links_unavailable'):
                    failures += 1
                article = {k: row[k] for k in ('title', 'source_url', 'source', 'published')}
                article.update(source_name=source_catalog[source]['name'], channel=row['channel'], feed_url=row.get('feed_url'), date_inferred=row.get('date_inferred',False), paper_ids=list(links),
                               body_source=row.get('body_source', 'source'),
                               selection_text=row.get('body') or row.get('abstract') or d.clean_text(row.get('excerpt','')),
                               links_unavailable=row.get('links_unavailable', False))
                reports_by_url[article['source_url']] = article
                for ident, url in links.items():
                    found.add(ident)
                    paper = papers.setdefault(ident, {'id': ident, 'title': ('arXiv · ' + ident) if url.startswith('https://arxiv.org/') else url,
                        'source': 'chinese', 'kind': 'paper', 'source_url': url, 'paper_url': url, 'authors': [], 'abstract': '', 'reports': [],
                        'evidence_scope': '报道中的论文链接'})
                    report = {k: row[k] for k in ('title', 'source_url', 'source', 'published')}
                    report.update(source_name=source_catalog[source]['name'], channel=row['channel'], feed_url=row.get('feed_url'), date_inferred=row.get('date_inferred',False))
                    if report not in paper['reports']:
                        paper['reports'].append(report)
            statuses.append({'source': source, 'ok': not listing_failed and failures == 0, 'count': len(found), 'articles': sum(a['source'] == source for a in reports_by_url.values()),
                             'message': coverage + (f'；{failures} 篇正文未读取，结果不完整' if failures else '')})
    from . import daily_filter
    require_enabled()
    if news_sources.signature() != news_sources.signature(sources):
        raise ValueError('关注来源已修改，请按新来源刷新动态')
    evidence.save()
    selected, filtering = daily_filter.select(list(reports_by_url.values()))
    pool = limit_articles(selected, limit=None)
    selected = limit_articles(pool)
    pool_urls = {a['source_url'] for a in pool}
    paper_pool = [{**p, 'reports': [r for r in p['reports'] if r['source_url'] in pool_urls]} for p in papers.values()]
    paper_pool = [p for p in paper_pool if p['reports']]
    reports_by_url = {a['source_url']: a for a in selected}
    for paper in papers.values():
        paper['reports'] = [r for r in paper['reports'] if r['source_url'] in reports_by_url]
    papers = {k:p for k,p in papers.items() if p['reports']}
    from . import news_metadata
    try:
        previous_papers = {p['id']: p for p in store.get('daily', 'latest').get('items', [])}
    except ValueError:
        previous_papers = {}
    for ident, paper in papers.items():
        old = previous_papers.get(ident, {})
        if old and old.get('source_url') == paper['source_url'] and not news_metadata.unresolved(old):
            paper.update({k: old[k] for k in ('title', 'abstract', 'authors', 'published', 'metadata_status', 'metadata_source') if k in old})
    try:
        info = metadata([k for k,p in papers.items() if not k.startswith('https://') and news_metadata.unresolved(p)])
        for ident, values in info.items():
            if ident in papers:
                papers[ident].update(values)
    except Exception:
        pass  # Missing entries are resolved independently below.
    papers = {p['id']: p for p in news_metadata.enrich(papers.values(), check=require_enabled)}
    missing = sum(news_metadata.unresolved(p) for p in papers.values())
    metadata_error = f'{missing} 篇论文标题暂未获取，可通过报道出处查看原文。' if missing else ''
    items = sorted(papers.values(), key=lambda p: max(stamp(r['published']) for r in p['reports']), reverse=True)
    return {'id': 'latest', 'updated_at': now.isoformat(), 'items': items, 'paper_pool': [{**p, **{k:v for k,v in papers.get(p['id'], {}).items() if k != 'reports'}} for p in paper_pool], 'article_pool': pool, 'articles': sorted(reports_by_url.values(), key=lambda a: stamp(a['published']), reverse=True), 'source_status': statuses, 'note': metadata_error, 'window_hours':WINDOW_HOURS, 'source_version': SOURCE_VERSION, 'filtering': filtering, 'sources_signature': news_sources.signature(sources), 'web_supplement': web.summary(), 'cache_reused_articles': evidence.reused}


def cached():
    if not enabled():
        return disabled_result()
    try:
        value = store.get('daily', 'latest')
    except ValueError:
        return {'items': [], 'articles': [], 'source_status': [], 'updated_at': None, 'stale': True}
    now = utcnow()
    if value.get('source_version') != SOURCE_VERSION:
        return {'items': [], 'articles': [], 'source_status': [], 'updated_at': None, 'stale': True}
    sources = news_sources.current()
    selected_sources = set(sources['selected'])
    value['source_status'] = [s for s in value.get('source_status', []) if s['source'] in selected_sources]
    value['article_pool'] = limit_articles([a for a in value.get('article_pool', value.get('articles', [])) if a.get('source') in selected_sources and is_article(a) and a.get('selection_reason') and recent(a['published'], now)], limit=None)
    value = limit_edition(value)
    selected_urls = {a['source_url'] for a in value['articles']}
    value['items'] = [{**p, 'reports': [r for r in p['reports'] if r['source_url'] in selected_urls and recent(r['published'], now)]} for p in value['items']]
    value['items'] = [p for p in value['items'] if p['reports']]
    from .daily_filter import context_signature
    value['stale'] = value.get('sources_signature', news_sources.signature(news_sources.defaults())) != news_sources.signature(sources) or value.get('filtering',{}).get('context_signature') != context_signature()[0] or bool(stamp(value['updated_at']) and stamp(value['updated_at']).astimezone(LOCAL_ZONE).date() != now.astimezone(LOCAL_ZONE).date()) or value.get('source_version') != SOURCE_VERSION or value.get('window_hours') != WINDOW_HOURS or not stamp(value['updated_at']) or (now - stamp(value['updated_at'])).total_seconds() >= TTL
    return value


def refresh(force=False):
    require_enabled()
    with LOCK:
        require_enabled()
        previous = cached()
        # Debounce manual double clicks as well as automatic refreshes across tabs.
        age = (utcnow() - stamp(previous['updated_at'])).total_seconds() if previous.get('updated_at') else TTL
        if not previous['stale'] and (not force or age < 60):
            return repair_metadata(previous)
        source_signature = news_sources.signature()
        result = collect()
        if news_sources.signature() != source_signature:
            raise ValueError('关注来源已修改，请按新来源刷新动态')
        require_enabled()  # A setting change cannot publish an in-flight refresh.
        result['sources_signature'] = source_signature
        result['window_hours'] = WINDOW_HOURS
        result['source_version'] = SOURCE_VERSION
        # Keep still-current cached papers when a source failed during refresh.
        failed = {s['source'] for s in result['source_status'] if not s['ok']}
        if not result.get('filtering',{}).get('ok',False):
            failed.update(news_sources.current()['selected'])
        # Only preserve selections made for the same profile and model context.
        if previous.get('filtering',{}).get('context_signature') != result.get('filtering',{}).get('context_signature'):
            previous = {**previous, 'items': [], 'articles': [], 'article_pool': [], 'paper_pool': [], 'extra_urls': []}
        by_id = {p['id']: p for p in result['items']}
        for old in previous['items']:
            reports = [{**r, 'cached': True} for r in old['reports'] if r['source'] in failed]
            if reports:
                if old['id'] not in by_id:
                    by_id[old['id']] = {**old, 'reports': []}
                for r in reports:
                    if not any(x['source_url'] == r['source_url'] for x in by_id[old['id']]['reports']):
                        by_id[old['id']]['reports'].append(r)
        result['items'] = list(by_id.values())
        articles_by_url = {a['source_url']: a for a in result.get('articles', [])}
        for old in previous.get('articles', []):
            if old['source'] in failed and old['source_url'] not in articles_by_url:
                articles_by_url[old['source_url']] = {**old, 'cached': True}
        result['articles'] = list(articles_by_url.values())
        result['extra_urls'] = previous.get('extra_urls', []) if previous.get('filtering', {}).get('context_signature') == result.get('filtering', {}).get('context_signature') else []
        retained_pool = [a for a in previous.get('article_pool', []) if a['source'] in failed]
        result['article_pool'] = limit_articles(result.get('article_pool', []) + result['articles'] + retained_pool, limit=None)
        pool_papers = {p['id']: p for p in result.get('paper_pool', [])}
        retained_papers = [{**p, 'reports': [r for r in p['reports'] if r['source'] in failed]}
                           for p in previous.get('paper_pool', [])]
        for p in result['items'] + retained_papers:
            if not p['reports']: continue
            if p['id'] not in pool_papers:
                pool_papers[p['id']] = p
            else:
                existing = pool_papers[p['id']]
                reports = {r['source_url']:r for r in p['reports']}
                reports.update({r['source_url']:r for r in existing['reports']})
                existing['reports'] = list(reports.values())
        result['paper_pool'] = list(pool_papers.values())
        result = limit_edition(result)
        require_enabled()
        with store.LOCK:
            if news_sources.signature() != source_signature:
                raise ValueError('关注来源已修改，请按新来源刷新动态')
            store.save('daily', result)
        return cached()


def repair_metadata(value=None):
    """Update names in an existing edition without news retrieval or model filtering."""
    from . import news_metadata
    require_enabled()
    value = value if value is not None else cached()
    items = news_metadata.enrich(value['items'], check=require_enabled)
    missing = sum(news_metadata.unresolved(p) for p in items)
    repaired = {p['id']: p for p in items}
    pool = [{**p, **{k:v for k,v in repaired.get(p['id'], {}).items() if k != 'reports'}} for p in value.get('paper_pool', items)]
    result = {**value, 'paper_pool': pool, 'items': items, 'note': f'{missing} 篇论文标题暂未获取，可通过报道出处查看原文。' if missing else ''}
    require_enabled()
    if result != value:
        with store.LOCK:
            require_enabled()
            try:
                latest = store.get('daily', 'latest')
            except ValueError:
                latest = None
            if latest and (latest.get('updated_at') != value.get('updated_at') or latest.get('sources_signature') != value.get('sources_signature')):
                return cached()  # Do not overwrite an edition refreshed during metadata lookup.
            store.save('daily', result)
    return result
