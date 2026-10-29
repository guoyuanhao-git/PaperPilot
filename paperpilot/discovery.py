import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

LOCK = threading.Lock()
LAST_REQUEST = 0
UA = {'User-Agent': 'PaperPilot/0.1 (local personal research tool)'}


def arxiv_id(url):
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme != 'https' or parsed.hostname not in ('arxiv.org', 'www.arxiv.org'):
        raise ValueError('链接导入目前支持 https://arxiv.org/abs/... 或 /pdf/...；其他论文请上传 PDF')
    match = re.fullmatch(r'/(?:abs|pdf)/((?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?)(?:\.pdf)?', parsed.path)
    if not match:
        raise ValueError('无法识别 arXiv 论文地址')
    return match[1]


def download(url):
    ident = arxiv_id(url)
    with urllib.request.urlopen(urllib.request.Request('https://arxiv.org/pdf/' + ident, headers=UA), timeout=60) as response:
        if urllib.parse.urlparse(response.url).hostname not in ('arxiv.org', 'www.arxiv.org'):
            raise ValueError('论文下载重定向到了不支持的地址')
        data = response.read(40 * 1024 * 1024 + 1)
    return data, ident + '.pdf', 'https://arxiv.org/abs/' + ident


def import_url(value):
    """Accept an arXiv identifier or official link, always download from canonical HTTPS."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('请输入 arXiv ID 或完整论文链接')
    value = value.strip()
    if re.match(r'(?i)^https?://', value):
        p = urllib.parse.urlsplit(value)
        if p.hostname not in ('arxiv.org', 'www.arxiv.org') or p.username or p.password or p.port not in (None, 80, 443):
            raise ValueError('仅支持 arXiv 官方论文链接或 arXiv ID')
        path = p.path
        if not path.startswith(('/abs/', '/pdf/')):
            path = '/abs/' + path.lstrip('/')
        ident = arxiv_id('https://arxiv.org' + path)
    else:
        ident = arxiv_id('https://arxiv.org/abs/' + re.sub(r'(?i)^arxiv:\s*', '', value))
    return 'https://arxiv.org/abs/' + ident


def search(query, recent_days=0, count=10, sort_by='submittedDate'):
    global LAST_REQUEST
    query = query.strip()
    if not query or len(query) > 1000:
        raise ValueError('检索条件不能为空，最多 1000 字符')
    if not re.search(r'\b(?:all|ti|au|cat|abs):', query):
        # Prefix each quoted term / OR phrase, rather than silently searching an empty query.
        query = ' OR '.join('all:' + part.strip() for part in re.split(r'\s+OR\s+', query) if part.strip())
    if recent_days:
        since = (datetime.now(timezone.utc) - timedelta(days=recent_days)).strftime('%Y%m%d0000')
        query = '(' + query + ') AND submittedDate:[' + since + ' TO 300001010000]'
    if sort_by not in ('submittedDate', 'relevance'):
        raise ValueError('不支持的论文排序方式')
    url = 'https://export.arxiv.org/api/query?' + urllib.parse.urlencode({'search_query': query, 'start': 0, 'max_results': min(60, count), 'sortBy': sort_by, 'sortOrder': 'descending'})
    with LOCK:
        time.sleep(max(0, 3 - (time.monotonic() - LAST_REQUEST)))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=35) as response:
                raw = response.read(2 * 1024 * 1024)
        finally:
            LAST_REQUEST = time.monotonic()
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    results = []
    for entry in ET.fromstring(raw).findall('a:entry', ns):
        value = lambda key: ' '.join((entry.findtext('a:' + key, '', ns)).split())
        address = value('id').replace('http://', 'https://')
        try:
            ident = arxiv_id(address)
        except ValueError:
            continue
        results.append({'id': ident, 'title': value('title'), 'abstract': value('summary'), 'source_url': address,
                        'published': value('published'), 'updated': value('updated'),
                        'authors': [a.findtext('a:name', '', ns) for a in entry.findall('a:author', ns)],
                        'evidence_scope': 'arXiv 元信息与摘要；未读全文'})
    return results

# Public source adapters. Keep provenance and distinguish news reports from papers.
import json
from html.parser import HTMLParser
from email.utils import parsedate_to_datetime
from concurrent.futures import ThreadPoolExecutor

SOURCES = {
    'arxiv': {'name': 'arXiv', 'icon': '/icons/arxiv.png', 'url': 'https://arxiv.org', 'kind': 'paper'},
    'huggingface': {'name': '🤗 DailyPapers', 'url': 'https://huggingface.co/papers', 'kind': 'paper'},
    'semantic_scholar': {'name': 'Semantic Scholar', 'url': 'https://www.semanticscholar.org', 'kind': 'paper'},
    'crossref': {'name': 'Crossref', 'url': 'https://www.crossref.org', 'kind': 'paper'},
    'hf_papers': {'name': '🤗 Papers', 'url': 'https://huggingface.co/papers', 'kind': 'paper'},
    'official_papers': {'name': '官方论文来源', 'url': 'https://proceedings.neurips.cc', 'kind': 'paper'},
    'deepseek_web': {'name': '联网补充 · 原始论文来源', 'url': 'https://api.deepseek.com', 'kind': 'paper'},
    'papers_cool': {'name': 'CoolPapers', 'icon': '/icons/papers-cool.ico', 'url': 'https://papers.cool', 'kind': 'paper'},
    'jushenjiyuan': {'name': '具身纪元', 'url': 'https://mp.weixin.qq.com/s/lX2hWnCPNyIK5saoWG6_AQ', 'kind': 'news'},
    'qbitai': {'name': '量子位', 'url': 'https://www.qbitai.com', 'kind': 'news'},
    'aiera': {'name': '新智元', 'url': 'https://aiera.com.cn', 'kind': 'news'},
    'jiqizhixin': {'name': '机器之心', 'url': 'https://www.jiqizhixin.com', 'kind': 'news'},
    'shenlan': {'name': '深蓝具身智能', 'url': 'https://www.shenlanxueyuan.com/news?column_id=2&sort=latest', 'kind': 'news'},
    'leaderobot': {'name': '机器人大讲堂', 'url': 'https://wx.leaderobot.com/', 'kind': 'news'},
    'embodied': {'name': '具身智能之心', 'url': 'https://blog.csdn.net/qq_29462849', 'kind': 'news'},
}

# Public publisher identities; unavailable entries remain selectable without inventing feeds.
NEWS_GROUPS = {
    '中文三大会': ('jiqizhixin', 'aiera', 'qbitai'),
    '其他科技公众号': ('deeptech', 'aitechreview', 'zfinance', 'zpotentials', 'jazzyear', 'agiera', 'cvmart', 'zhidingai'),
    '具身智能': ('xbotics', 'embodied', 'jushenjiyuan', 'shenlan', 'sourcemind', 'robovibe', 'physicalai', 'shima'),
    '其他来源': ('leaderobot',),
}
SOURCES.update({
    'deeptech': {'name': 'DeepTech深科技', 'url': 'https://www.deeptechchina.com', 'kind': 'news', 'availability': '公众号 RSS'},
    'aitechreview': {'name': 'AI科技评论', 'url': 'https://mp.weixin.qq.com', 'kind': 'news', 'availability': '公众号 RSS'},
    **{ident: {'name': name, 'url': address, 'kind': 'news', 'availability': '待接入公开来源'}
       for ident, name, address in (
        ('zfinance', 'Z Finance', 'https://mp.weixin.qq.com'),
        ('zpotentials', 'Z Potentials', 'https://mp.weixin.qq.com'),
        ('jazzyear', '甲子光年', 'https://www.jazzyear.com'),
        ('agiera', '智能纪元AGI', 'https://mp.weixin.qq.com'),
        ('cvmart', '极市平台', 'https://www.cvmart.net'),
        ('zhidingai', '至顶AI实验室', 'https://www.zhiding.cn/zd-ai-lab/'),
        ('xbotics', 'Xbotics具身智能实验室', 'https://xbotics-embodied.site'),
        ('sourcemind', 'SourceMind', 'https://mp.weixin.qq.com/s/v0rYIjjoiW7bZMWXmswhKg'),
        ('robovibe', '罗博脉动RoboVibe', 'https://mp.weixin.qq.com/s/2lcpp9IhNlTBqHauJFg8_A'),
        ('physicalai', '物理AI之心', 'https://mp.weixin.qq.com/s/UR5UkPqMDLQ3At5bp1dFPQ'),
        ('shima', '石麻笔记', 'https://mp.weixin.qq.com/s/MoRIc83pmSDcZh_9pg3QgA'),
    )},
})
for identifier in ('jazzyear', 'zpotentials'):
    SOURCES[identifier]['availability'] = '第三方 RSS'
SOURCES['zhidingai']['availability'] = '官方专栏'
SOURCES['xbotics'].update(url='https://www.x-techcon.com/author/190.html', availability='公开转载 · 科技区角')
SOURCES['jushenjiyuan']['availability'] = '待接入公开来源'
for group, identifiers in NEWS_GROUPS.items():
    for identifier in identifiers:
        SOURCES[identifier]['group'] = group

SEARCH_SOURCES = ('arxiv', 'huggingface', 'papers_cool')


def validate_search_sources(sources):
    values = validate_sources(sources)
    if any(s not in SEARCH_SOURCES for s in values):
        raise ValueError('按需筛选支持 arXiv、🤗 DailyPapers 和 CoolPapers；公众号请查看每日动态')
    return values


def validate_count(count):
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 20:
        raise ValueError('推荐条目数须为 1–20 的整数')
    return count


def validate_sources(sources):
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or s not in SOURCES for s in sources):
        raise ValueError('请选择至少一个可用信息源')
    return list(dict.fromkeys(sources))


def public_fetch(url, hosts, headers=None, *, timeout=25, encoding='utf-8-sig'):
    def check(value):
        p = urllib.parse.urlparse(value)
        if p.scheme != 'https' or p.hostname not in hosts or p.port not in (None, 443) or p.username or p.password:
            raise ValueError('信息源跳转到不支持的地址')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    check(url)
    with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers={**UA, **(headers or {})}), timeout=timeout) as response:
        data = response.read(3 * 1024 * 1024 + 1)
    if len(data) > 3 * 1024 * 1024:
        raise ValueError('信息源响应过大')
    return data.decode(encoding)


def clean_text(value):
    class Text(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts = []; self.skip = 0
        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'):
                self.skip += 1
        def handle_endtag(self, tag):
            if tag in ('script', 'style'):
                self.skip = max(0, self.skip - 1)
        def handle_data(self, data):
            if not self.skip:
                self.parts.append(data)
    parser = Text(); parser.feed(value)
    return ' '.join(' '.join(parser.parts).split())


def rss_items(raw, source):
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise ValueError('该来源当前未提供公开 RSS；请通过官网数据服务获取访问权限') from None
    if root.tag != 'rss':
        raise ValueError('该来源当前返回数据服务页面，尚未获得新闻列表')
    results = []
    for item in root.findall('./channel/item')[:50]:
        url = (item.findtext('link') or '').strip()
        domain = urllib.parse.urlparse(url).hostname
        if urllib.parse.urlparse(url).scheme != 'https' or domain not in ({'www.qbitai.com', 'qbitai.com'} if source == 'qbitai' else {'www.jiqizhixin.com', 'jiqizhixin.com'}):
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate')).isoformat()
        except (ValueError, TypeError):
            published = ''
        results.append({'id': source + ':' + url, 'title': clean_text(item.findtext('title') or ''),
                        'abstract': clean_text(item.findtext('description') or '')[:1800], 'source_url': url,
                        'published': published, 'authors': [], 'source': source, 'kind': 'news',
                        'evidence_scope': SOURCES[source]['name'] + '公开标题与摘要；媒体报道，未核实论文原文'})
    return results


def hf_items(raw):
    rows = json.loads(raw)
    if not isinstance(rows, list):
        raise ValueError('Hugging Face 返回格式发生变化')
    results = []
    for row in rows:
        paper = row.get('paper', {})
        ident = paper.get('id', '')
        try:
            arxiv_id('https://arxiv.org/abs/' + ident)
        except ValueError:
            continue
        results.append({'id': ident, 'title': paper.get('title') or row.get('title', ''),
                        'abstract': (paper.get('summary') or row.get('summary', ''))[:5000],
                        'source_url': 'https://huggingface.co/papers/' + ident, 'paper_url': 'https://arxiv.org/abs/' + ident,
                        'published': paper.get('publishedAt', row.get('publishedAt', '')), 'daily_at': paper.get('submittedOnDailyAt') or row.get('submittedOnDailyAt') or row.get('publishedAt', ''),
                        'authors': [a['name'] for a in paper.get('authors', []) if a.get('name')],
                        'source': 'huggingface', 'kind': 'paper', 'upvotes': paper.get('upvotes', 0),
                        'evidence_scope': 'Hugging Face Daily Papers 收录与摘要；社区票数仅作热度线索，未读全文'})
    return results


def aiera_items(raw, today=None):
    match = re.search(r'\bvar\s+FEED\s*=\s*', raw)
    if not match:
        raise ValueError('新智元公开页面格式发生变化')
    # Parse the embedded JSON array as data; never execute site JavaScript.
    rows, _ = json.JSONDecoder().raw_decode(raw[match.end():])
    today = today or datetime.now(timezone(timedelta(hours=8)))
    results = []
    for row in rows[:100]:
        if not isinstance(row, list) or len(row) < 6 or not all(isinstance(v, str) for v in row[:6]):
            continue
        if row[4] != '新智元':
            continue  # This page also aggregates other outlets; keep source identity truthful.
        if not re.fullmatch(r'[a-zA-Z0-9_-]+', row[5]):
            continue
        try:
            month, day = map(int, row[1].split('/'))
            hour, minute = map(int, row[0].split(':'))
            published = today.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if published > today + timedelta(days=1):
                published = published.replace(year=today.year - 1)
        except ValueError:
            continue
        results.append({'id': 'aiera:' + row[5], 'title': row[2], 'abstract': row[3],
                        'source_url': 'https://aiera.com.cn/asi-item.html?id=' + row[5], 'published': published.isoformat(),
                        'date_inferred': True, 'authors': [], 'source': 'aiera', 'kind': 'news',
                        'evidence_scope': '新智元公开新闻列表与摘要；原站只标月日，年份按最近日期推定；未核实原始研究'})
    return results


def cool_feed(query, days, count):
    from .title_search import cool_items
    # The public search UI tokenizes words. Query each OR branch independently,
    # then let recommendation assess the original request against real abstracts.
    parts = re.split(r'\s+OR\s+', query, flags=re.I)
    queries = []
    for part in parts:
        part = re.sub(r'\b(?:all|ti|abs|au|cat):|\b(?:AND|NOT)\b', ' ', part, flags=re.I)
        terms = ' '.join(re.findall(r'\w+', part))
        if terms and terms not in queries:
            queries.append(terms)
    if len(queries) > 4:
        raise ValueError('CoolPapers 最多支持 4 组 OR 条件，请精简检索需求')
    if not queries:
        raise ValueError('CoolPapers 检索需求不能为空')
    since = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat() if days else ''
    groups, seen = [], set()
    for terms in queries:
        url = 'https://papers.cool/arxiv/search?' + urllib.parse.urlencode({'query': terms})
        rows = cool_items(public_fetch(url, {'papers.cool'}))
        group = []
        for row in rows:
            if since and (not row['published'] or not since <= row['published'][:10] <= datetime.now(timezone.utc).date().isoformat()):
                continue
            try:
                row['id'] = arxiv_id(row['paper_url'])
            except ValueError:
                continue
            canonical = re.sub(r'v\d+$', '', row['id'])
            if canonical not in seen:
                group.append(row); seen.add(canonical)
        groups.append(group)
    return [g[i] for i in range(max(map(len, groups), default=0)) for g in groups if i < len(g)][:count]


def feed(source, query, days, count=10):
    if source == 'arxiv':
        return [{**p, 'source': 'arxiv', 'kind': 'paper', 'paper_url': p['source_url']} for p in search(query, days, count)]
    if source == 'papers_cool':
        return cool_feed(query, days, count)
    if source == 'huggingface':
        rows = hf_items(public_fetch('https://huggingface.co/api/daily_papers?limit=50', {'huggingface.co'}))
    elif source == 'qbitai':
        rows = rss_items(public_fetch('https://www.qbitai.com/feed', {'www.qbitai.com', 'qbitai.com'}), source)
    elif source == 'aiera':
        rows = aiera_items(public_fetch('https://aiera.com.cn/', {'aiera.com.cn', 'www.aiera.com.cn'}))
    elif source == 'jiqizhixin':
        rows = rss_items(public_fetch('https://www.jiqizhixin.com/rss', {'www.jiqizhixin.com', 'jiqizhixin.com'}), source)
    else:
        raise ValueError('未知信息源')
    if days:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = [r for r in rows if r.get('published') and datetime.fromisoformat(r['published'].replace('Z', '+00:00')).astimezone(timezone.utc) >= since]
    terms = re.findall(r'[a-zA-Z]{3,}|[\u4e00-\u9fff]{2,}', query.lower())
    terms = [t for t in terms if t not in ('all', 'and', 'the')]
    def score(row):
        text = (row['title'] + ' ' + row['abstract']).lower()
        return sum(text.count(t) for t in terms)
    return sorted(rows, key=score, reverse=True)[:count]


def collect(sources, query, days, arxiv_query=None, count=10):
    sources = validate_sources(sources)
    output, states = [], []
    with ThreadPoolExecutor(max_workers=5) as pool:
        tasks = {s: pool.submit(feed, s, (arxiv_query or query) if s in ('arxiv', 'papers_cool') else query, days, count) for s in sources}
        for source, task in tasks.items():
            try:
                rows = task.result()
                states.append({'source': source, 'ok': True, 'count': len(rows), 'message': 'CoolPapers arXiv 检索列表；按论文发表日期筛选，公开候选覆盖有限' if source == 'papers_cool' else ('检索结果' if source == 'arxiv' else '最近公开列表；时间筛选不代表完整历史检索')})
                output.append(rows)
            except Exception as e:
                message = str(e) if isinstance(e, ValueError) else '暂时无法访问，请稍后重试或查看官网'
                states.append({'source': source, 'ok': False, 'count': 0, 'message': message[:200]})
    # Interleave so a busy feed does not crowd out other user-selected sources.
    candidates, seen = [], set()
    for i in range(count):
        for rows in output:
            if i >= len(rows):
                continue
            ident = re.sub(r'v\d+$', '', rows[i]['id']) if rows[i].get('kind') == 'paper' else rows[i]['id']
            if ident not in seen:
                candidates.append(rows[i]); seen.add(ident)
                if len(candidates) >= max(20, count):
                    return candidates, states
    return candidates, states
