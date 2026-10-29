"""Publisher website adapters; public articles are candidates, not WeChat pushes."""
import json
import re
import html
from contextvars import ContextVar
from datetime import timedelta, timezone
from urllib.parse import urlparse, urljoin
from . import discovery as d
from .daily import stamp, recent, window_start, paper_links, Body


SINCE = ContextVar("news_since", default=None)

def listing_start(now):
    return SINCE.get() or window_start(now)

def article_body(raw, source):
    parser = Body({'qbitai':'article', 'shenlan':'sl-news-article__body', 'leaderobot':'article', 'zhidingai':'txts', 'xbotics':'article-body-wrap'}.get(source,'content_views'))
    parser.feed(raw)
    if not parser.found:
        raise ValueError('正文格式变化，暂未读取')
    return ''.join(parser.parts)


def csdn_rows(raw):
    rows = []
    for block in re.findall(r'<article\b[^>]*>.*?</article>', raw, re.S):
        link = re.search(r'https://blog\.csdn\.net/qq_29462849/article/details/\d+', block)
        date = re.search(r'(\d{4})\.(\d{2})\.(\d{2})', block)
        title = re.search(r'<h4[^>]*>(.*?)</h4>', block, re.S)
        if link and date and title:
            rows.append({'source_url': link[0], 'title': d.clean_text(title[1]), 'source': 'embodied',
                         'published': '-'.join(date.groups()) + 'T00:00:00+08:00', 'date_inferred': True})
    if not rows:
        raise ValueError('同名作者公开主页格式变化或无法读取')
    return rows


def shenlan_rows(raw):
    rows = []
    for block in re.findall(r'<article\b[^>]*class="sl-news-item"[^>]*>.*?</article>', raw, re.S):
        link = re.search(r'href="(/news/detail/\d+)"', block)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.S)
        date = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        if link and title and date and stamp(date[1]):
            rows.append({'source': 'shenlan', 'source_url': 'https://www.shenlanxueyuan.com' + link[1],
                         'title': d.clean_text(title[1]), 'published': date[1], 'date_inferred': False})
    if not rows:
        raise ValueError('深蓝具身智能公开列表格式变化，未能读取文章时间')
    return rows


def leaderobot_data(raw):
    match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', raw, re.S)
    if not match:
        raise ValueError('机器人大讲堂公开页面格式变化')
    try:
        return json.loads(match[1])['props']['pageProps']['fallback']
    except (ValueError, KeyError, TypeError):
        raise ValueError('机器人大讲堂文章元信息暂不可读') from None


def leaderobot_row(value):
    published = str(value.get('publishTime') or '')
    created = str(value.get('createTime') or '')
    # Prefer original published day; never substitute a more recent edit time.
    if len(published) == 10:
        published = created if created.startswith(published) else published + ' 00:00:00'
    published = published.replace(' ', 'T')
    if published and not stamp(published):
        published += '+08:00'
    if not stamp(published) or not isinstance(value.get('id'), int) or not isinstance(value.get('title'), str):
        raise ValueError('未找到机器人大讲堂文章的原始发布时间')
    return {'source': 'leaderobot', 'source_url': 'https://wx.leaderobot.com/news/' + str(value['id']),
            'title': value['title'], 'published': published, 'date_inferred': len(str(value.get('publishTime') or '')) == 10}


def specialist_articles(source, now):
    if source == 'shenlan':
        result, seen, covered = [], set(), False
        for page in range(1, 21):
            raw = d.public_fetch(d.SOURCES[source]['url'] + '&page=' + str(page), {'www.shenlanxueyuan.com', 'shenlanxueyuan.com'})
            rows = shenlan_rows(raw)
            fresh = [r for r in rows if r['source_url'] not in seen]
            if not fresh:
                break
            seen.update(r['source_url'] for r in fresh)
            result.extend(r for r in fresh if recent(r['published'], now))
            if any(stamp(r['published']) < listing_start(now) for r in fresh):
                covered = True; break
            if not re.search(r'page=' + str(page + 1) + r'(?:["&]|$)', html.unescape(raw)):
                covered = True; break
        return result, '深蓝学院官网具身智能专栏；' + ('已读取至三日前或列表末尾' if covered else '仅获取部分公开列表') + '；不代表微信独占推送'
    data = leaderobot_data(d.public_fetch(d.SOURCES[source]['url'], {'wx.leaderobot.com', 'www.leaderobot.com'}))
    rows = {}
    for key, section in data.items():
        if '"newsList"' not in key or not isinstance(section, dict):
            continue
        for value in section.get('items', []):
            row = leaderobot_row(value)
            rows[row['source_url']] = row
    if not rows:
        raise ValueError('机器人大讲堂官网未返回可核实发布时间的文章')
    latest = max(r['published'] for r in rows.values())[:10]
    return [r for r in rows.values() if recent(r['published'], now)], f'机器人大讲堂官网可见列表，最新文章 {latest}；未确认覆盖完整三日，不代表微信完整推送'


def verified_publisher_rows(raw, source):
    """Only the verified publisher's article cards, never sidebar recommendations."""
    if source == 'xbotics':
        if not re.search(r'<h1[^>]*>\s*(?:Xbot具身知识库|Xbotics具身智能实验室)\s*</h1>', raw):
            raise ValueError('Xbotics 转载栏目身份不匹配')
        raw = raw.split('data-author-id="190"', 1)[-1]
        pattern = r'<article\b[^>]*article-content-item[^>]*>.*?</article>'
        link_pattern = r'href="(https://www\.x-techcon\.com/article/\d+\.html)"'
    else:
        if '<title>至顶AI实验室-' not in raw:
            raise ValueError('至顶 AI 实验室栏目身份不匹配')
        pattern = r'<article\b[^>]*feed-item[^>]*>.*?</article>'
        link_pattern = r'href="((?://www\.zhiding\.cn)?/zd-ai-lab/\d{4}/\d{4}/\d+\.shtml)"'
    rows = []
    for block in re.findall(pattern, raw, re.S):
        link = re.search(link_pattern, block)
        title = re.search(r'<h3[^>]*>(.*?)</h3>', block, re.S)
        date = (re.search(r'>(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})</p>', block) if source == 'xbotics'
                else re.search(r'class="times">(\d{4}-\d{2}-\d{2})</div>', block))
        if link and title and date:
            value = date[1].replace(' ', 'T')
            if len(value) == 10: value += 'T00:00:00'
            if not stamp(value + '+08:00'): continue
            rows.append({'source': source, 'source_url': urljoin(d.SOURCES[source]['url'], link[1]),
                         'title': d.clean_text(title[1]), 'published': value + '+08:00',
                         'date_inferred': source == 'zhidingai'})
    if not rows: raise ValueError('公开栏目格式变化，未找到带时间的文章')
    return rows


def verified_publisher_articles(source, now):
    address = d.SOURCES[source]['url']
    encoding = 'gb18030' if source == 'zhidingai' else 'utf-8-sig'
    rows = verified_publisher_rows(d.public_fetch(address, {urlparse(address).hostname}, encoding=encoding), source)
    latest = max(r['published'] for r in rows)[:10]
    provenance = '至顶 AI 实验室官网专栏' if source == 'zhidingai' else '科技区角 Xbotics 公开转载栏目，日期按转载页面时间'
    return [r for r in rows if recent(r['published'], now)], provenance + f'；列表最新 {latest}，不保证覆盖微信全部推送'


def website_articles(source, now):
    """Return public recent reports plus truthful coverage information."""
    if source in ('zhidingai', 'xbotics'):
        return verified_publisher_articles(source, now)
    if source not in ('qbitai', 'aiera', 'jiqizhixin', 'embodied', 'shenlan', 'leaderobot'):
        raise ValueError(d.SOURCES[source]['name'] + '：暂未接入可持续读取的公开来源')
    if source in ('shenlan', 'leaderobot'):
        return specialist_articles(source, now)
    if source == 'aiera':
        rows = d.aiera_items(d.public_fetch('https://aiera.com.cn/', {'aiera.com.cn', 'www.aiera.com.cn'}), now.astimezone(timezone(timedelta(hours=8))))
        try:
            db = json.loads(d.public_fetch('https://aiera.com.cn/feed.json', {'aiera.com.cn'}))
        except Exception:
            db = {}  # Individual detail failures must not hide the public headlines.
        result = []
        for row in rows:
            if not recent(row['published'], now):
                continue
            ident = row['id'].split(':', 1)[1]
            detail = db.get(ident)
            if detail is not None:
                row['body'] = '\n'.join(detail.get('d', []) + [str(b[1]) for b in detail.get('b', []) if len(b) > 1 and b[0] != 'i'])
            result.append(row)
        return result, '官网近三日公开列表；年份由月日推定，无法保证覆盖微信独占推送'
    if source == 'embodied':
        rows = csdn_rows(d.public_fetch(d.SOURCES[source]['url'] + '?type=blog', {'blog.csdn.net'}))
        # Listing dates can be update dates: require exact original publication time below.
        cutoff = window_start(now).date()
        latest = max(r['published'][:10] for r in rows)
        rows = [r for r in rows if stamp(r['published']).date() >= cutoff]
        return rows, f'主页最近可见更新 {latest}；同名作者 CSDN 公开主页，正文按首次发布时间核验；不代表微信完整推送'
    rows, seen, covered = [], set(), False
    for page in range(1, 21):
        url = ('https://www.qbitai.com/feed' + (f'?paged={page}' if page > 1 else '')) if source == 'qbitai' else 'https://www.jiqizhixin.com/rss'
        batch = d.rss_items(d.public_fetch(url, {urlparse(d.SOURCES[source]['url']).hostname, urlparse(d.SOURCES[source]['url']).hostname.removeprefix('www.')}), source)
        fresh = [r for r in batch if r['source_url'] not in seen]
        if not fresh:
            covered = not batch
            break
        seen.update(r['source_url'] for r in fresh)
        rows.extend(r for r in fresh if recent(r['published'], now))
        if any(stamp(r['published']) and stamp(r['published']) < listing_start(now) for r in fresh):
            covered = True; break
        if source != 'qbitai':
            break
    return rows, ('已翻页读取至三日前' if covered else '仅获取当前公开列表，未确认覆盖完整三日') + '；不代表微信独占推送'


def read_website_article(row, now):
    if 'body' not in row and row['source'] == 'aiera':
        ident = row['id'].split(':', 1)[1]
        detail = json.loads(d.public_fetch(f'https://aiera.com.cn/d/{ident[:2].lower()}/{ident}.json', {'aiera.com.cn'}))
        row = {**row, 'body': '\n'.join(detail.get('d', []) + [str(b[1]) for b in detail.get('b', []) if len(b) > 1 and b[0] != 'i'])}
    if 'body' not in row:
        raw = d.public_fetch(row['source_url'], {urlparse(row['source_url']).hostname}, encoding='gb18030' if row['source']=='zhidingai' else 'utf-8-sig')
        if row['source'] == 'xbotics':
            header = raw.split('id="article-body-wrap"', 1)[0]
            if not re.search(r'href="https://www\.x-techcon\.com/author/190\.html"[^>]*>\s*(?:Xbotics具身智能实验室|Xbot具身知识库)\s*</a>', header):
                raise ValueError('转载文章作者身份不匹配')
            match = re.search(r'class="article-time"[^>]*>.*?(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', header, re.S)
            if not match: raise ValueError('转载文章缺少可核实的发布时间')
            row = {**row, 'published':match[1].replace(' ', 'T')+'+08:00'}
            if not recent(row['published'], now): return row, {}
        if row['source'] == 'zhidingai':
            header = raw.split('class="article-layout shell"', 1)[0]
            match = re.search(r'class="byline".*?(\d{4}-\d{2}-\d{2})', header, re.S)
            if not match or '至顶AI实验室' not in header: raise ValueError('文章身份或发布时间不可核实')
            row = {**row, 'published':match[1]+'T00:00:00+08:00'}
            if not recent(row['published'], now): return row, {}
        if row['source'] == 'shenlan':
            match = re.search(r'<time[^>]*datetime="([^"]+)"', raw)
            if not match or not stamp(match[1]):
                raise ValueError('深蓝文章未提供原始发布时间')
            row = {**row, 'published': match[1]}
            if not recent(row['published'], now):
                return row, {}
        if row['source'] == 'leaderobot':
            data = leaderobot_data(raw)
            ident = int(row['source_url'].rsplit('/', 1)[-1])
            value = next((v for k, v in data.items() if '"newsDetail"' in k and isinstance(v, dict) and v.get('id') == ident), None)
            if not value or not isinstance(value.get('content'), str):
                raise ValueError('机器人大讲堂正文暂不可读')
            row = leaderobot_row(value)
            if not recent(row['published'], now):
                return row, {}
            raw = '<div id="article">' + value['content'] + '</div>'
        if row['source'] == 'embodied':
            # CSDN exposes publication time in its structured article metadata.
            match = re.search(r'"datePublished"\s*:\s*"([^"]+)"', raw)
            if not match:
                match = re.search(r'class="time"[^>]*>\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})', raw)
            if not match:
                raise ValueError('未找到原始发布时间，未纳入近三日动态')
            value = match[1].replace(' ', 'T')
            if not stamp(value):
                value += '+08:00'
            if not recent(value, now):
                return row, {}
            row = {**row, 'published': value, 'date_inferred': False}
        row = {**row, 'body': article_body(raw, row['source'])}
    return row, paper_links(row['body'])
