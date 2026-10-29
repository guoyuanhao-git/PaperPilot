"""Opt-in, bounded DeepSeek Search/Fetch. Never used by graph generation.

Caches and request receipts live in the caller's account; no model or profile is
sent to these endpoints. A receipt is an estimate, not a provider invoice.
"""
import hashlib
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from . import store, providers, news_sources, discovery
from .classic_papers import CitationPage

LOCK = threading.Lock()
LAST_REQUEST = 0.0
DAILY_LIMIT = 60
PRICE = .005
PRIMARY_HOSTS = {'arxiv.org', 'papers.nips.cc', 'proceedings.neurips.cc',
                 'proceedings.mlr.press', 'openaccess.thecvf.com', 'aclanthology.org',
                 'openreview.net', 'dl.acm.org', 'ieeexplore.ieee.org'}


def enabled():
    return store.settings().get('web_supplement_enabled', False) is True


def day_id():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def usage():
    try:
        value = store.get('web_usage', day_id())
    except ValueError:
        value = {'id': day_id(), 'attempts': 0, 'successful': 0, 'unknown': 0}
    return {**value, 'estimated_cny': round(value['successful'] * PRICE, 3), 'limit': DAILY_LIMIT}


class Session:
    """One user action: title fallback (2/3) or news refresh (0/6)."""
    def __init__(self, *, searches=2, fetches=3):
        self.remaining = {'search': searches, 'fetch': fetches}
        self.receipts = []
        self.stopped = False

    def request(self, operation, body):
        global LAST_REQUEST
        # Check the live setting even when a task was started before it was turned off.
        if not enabled() or self.stopped:
            return {}
        key_id = hashlib.sha256(json.dumps([1, operation, body], sort_keys=True).encode()).hexdigest()
        with LOCK:
            if not enabled():
                return {}
            try:
                cached = store.get('web_cache', key_id)
            except ValueError:
                cached = {}
            if time.time() - cached.get('at', 0) < cached.get('ttl', 0):
                self.receipts.append({'operation': operation, 'cached': True, 'seconds': 0, 'estimated_cny': 0})
                return cached['value']
            if self.remaining[operation] <= 0:
                return {}
            config = store.settings()
            if config['deepseek']['base_url'].rstrip('/') not in ('https://api.deepseek.com', 'https://api.deepseek.com/v1'):
                self.stopped = True
                self.receipts.append({'operation': operation, 'error': '联网补充仅支持官方 DeepSeek API 地址'})
                return {}
            try:
                key = providers.api_key('deepseek')
            except ValueError:
                key = ''
            if not key:
                self.stopped = True
                self.receipts.append({'operation': operation, 'error': '联网补充需要当前用户的 DeepSeek Key'})
                return {}
            with store.LOCK:
                total = usage()
                if total['attempts'] >= DAILY_LIMIT:
                    self.receipts.append({'operation': operation, 'error': '今日联网补充已达到 60 次上限'})
                    self.stopped = True
                    return {}
                total['attempts'] += 1
                total['unknown'] += 1  # Remains unknown if the process exits during dispatch.
                store.save('web_usage', total)
            self.remaining[operation] -= 1
            time.sleep(max(0, .25 - (time.monotonic() - LAST_REQUEST)))
            started = time.monotonic()
            receipt = {'id': uuid.uuid4().hex, 'operation': operation, 'created_at': datetime.now(timezone.utc).isoformat(),
                       'cached': False, 'estimated_cny': 0, 'status': 'unknown'}
            # Record before dispatch, so an interruption never looks like no request.
            store.save('web_request', receipt)
            result = {}
            try:
                value = providers.post_json('https://api.deepseek.com/v1/tools/' + operation, body, key, timeout=20)
                if not isinstance(value, dict):
                    raise ValueError('联网补充返回格式无效')
                if operation == 'search':
                    if not isinstance(value.get('results'), list):
                        raise ValueError('联网补充返回格式无效')
                    value = {'results': [{k: str(r.get(k) or '')[:50000 if k == 'content' else 2000]
                                          for k in ('title', 'url', 'snippet', 'content')}
                                         for r in value['results'][:8] if isinstance(r, dict)]}
                elif not isinstance(value.get('content'), str):
                    raise ValueError('联网补充返回格式无效')
                else:
                    value = {'title': str(value.get('title') or '')[:2000], 'content': value['content'][:50000]}
                success = bool(value.get('results') if operation == 'search' else value.get('content'))
                receipt.update(status='success' if success else 'empty', estimated_cny=PRICE if success else 0)
                result = value
                store.save('web_cache', {'id': key_id, 'at': time.time(), 'ttl': 7 * 86400 if success else 900, 'value': value})
            except Exception as exc:
                message = str(exc) if isinstance(exc, ValueError) else '联网补充连接失败'
                # Timeouts may have completed remotely; don't report them as definitely free.
                known_failure = bool(re.search(r'HTTP \d{3}', message))
                receipt.update(status='failed' if known_failure else 'unknown', error=message[:180])
                self.stopped = True  # No automatic retries or repeated failures in this action.
                store.save('web_cache', {'id': key_id, 'at': time.time(), 'ttl': 900, 'value': {}})
            finally:
                LAST_REQUEST = time.monotonic()
                receipt['seconds'] = round(LAST_REQUEST - started, 2)
                store.save('web_request', receipt)
                # Attribute a response after midnight to the request's original day.
                total = store.get('web_usage', total['id'])
                total['successful'] += receipt['status'] == 'success'
                total['unknown'] -= receipt['status'] != 'unknown'
                store.save('web_usage', total)
                self.receipts.append(receipt)
            # Bound persisted page bodies/receipts; daily aggregates remain available.
            with store.LOCK, store.connect() as db:
                for kind, limit in (('web_cache', 200), ('web_request', 500)):
                    db.execute('DELETE FROM objects WHERE kind=? AND rowid NOT IN '
                               '(SELECT rowid FROM objects WHERE kind=? ORDER BY rowid DESC LIMIT ?)',
                               (kind, kind, limit))
            return result

    def search(self, query):
        # Preserve complete words within the endpoint's 128-character constraint.
        query = ' '.join(query.split())
        if len(query) > 128:
            query = query[:129].rsplit(' ', 1)[0][:128]
        return self.request('search', {'query': query, 'count': 8, 'need_content': True}).get('results', [])

    def fetch(self, url):
        address = news_sources.url(url)  # Never send local/private/credential-bearing URLs.
        return self.request('fetch', {'url': address})

    def summary(self):
        return {'requests': sum(not r.get('cached', False) and 'status' in r for r in self.receipts),
                'cache_hits': sum(r.get('cached', False) for r in self.receipts),
                'estimated_cny': round(sum(r.get('estimated_cny', 0) for r in self.receipts), 3),
                'seconds': round(sum(r.get('seconds', 0) for r in self.receipts), 2),
                'unknown': sum(r.get('status') == 'unknown' for r in self.receipts),
                'errors': list(dict.fromkeys(r['error'] for r in self.receipts if r.get('error')))}


def primary_url(value):
    """Only scholarly original pages may become paper cards; other hits stay leads."""
    try:
        value = news_sources.url(value)
        p = urlparse(value)
        if p.hostname in ('huggingface.co', 'papers.cool') or p.hostname == 'arxiv.org':
            match = re.search(r'/(?:papers|arxiv|abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?)', p.path)
            if match:
                return 'https://arxiv.org/abs/' + match[1]
        if p.hostname in PRIMARY_HOSTS and not p.path.lower().endswith('.pdf'):
            return value
    except ValueError:
        pass
    return ''


def markdown_text(value):
    # Fetch escapes punctuation even inside URLs (https\:\/\/arxiv\.org).
    # Decode Markdown escapes before interpreting headings or extracting links.
    return re.sub(r'\\([^\w\s])', r'\1', str(value or ''))


def verify_paper(hit, session):
    """Require citation metadata, or a paper heading literally present in original Markdown."""
    from .title_search import same_title
    url = primary_url(hit.get('url', ''))
    if not url:
        return None
    parser = CitationPage()
    try:
        parser.feed(discovery.public_fetch(url, {urlparse(url).hostname}, timeout=8))
    except Exception:
        pass
    title = parser.value('citation_title').strip()
    abstract = parser.value('citation_abstract') or ' '.join(parser.parts).strip()
    published = (parser.value('citation_date') or parser.value('citation_publication_date')).replace('/', '-')
    authors = parser.meta.get('citation_author', [])
    if not title:
        # Search summaries are not originals; use only content fetched for this exact URL.
        page = hit if hit.get('url') == url and hit.get('content') else session.fetch(url)
        body = markdown_text(page.get('content', ''))
        # arXiv title headings are identifiable; don't guess titles from arbitrary webpages.
        if urlparse(url).hostname != 'arxiv.org':
            return None
        expected = re.sub(r'^\[\d{4}\.\d{4,5}(?:v\d+)?\]\s*', '', str(page.get('title', '')))
        expected = re.sub(r'\s*[|–-]\s*arXiv.*$', '', expected, flags=re.I)
        headings = re.findall(r'^#{1,3}\s+(?:Title:\s*)?(.+)$', body, re.M)
        title = next((t.strip() for t in headings if same_title(t, expected)), '')
        if not title:
            return None
        # Keep extracted body separate from the abstract; never label a search summary as an abstract.
    if not 8 <= len(title) <= 500 or re.search(r'captcha|access denied|just a moment', title, re.I):
        return None
    ident = 'web-' + hashlib.sha256(url.encode()).hexdigest()[:20]
    return {'id': ident, 'title': title, 'source': 'deepseek_web', 'kind': 'paper',
            'paper_url': url, 'source_url': url, 'authors': authors, 'abstract': abstract,
            'published': published, 'pdf_url': '',
            'evidence_scope': 'DeepSeek 搜索补充；已核对原始论文页面标题，未读全文'}


def find_papers(query, session):
    """Bound verification work; unverified hits are links, never collectible paper cards."""
    from .title_search import normalize
    papers, leads, seen, checked = [], [], set(), 0
    for hit in session.search(query):
        if not isinstance(hit, dict):
            continue
        try:
            url = news_sources.url(hit.get('url'))
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        try:
            if primary_url(url) and checked < 3:
                checked += 1
                row = verify_paper(hit, session)
            else:
                row = None
        except Exception:
            row = None  # Optional enrichment never discards the baseline search results.
        if row:
            papers.append(row)
        elif hit.get('title'):
            target = normalize(query)
            text = normalize(str(hit['title']) + ' ' + str(hit.get('snippet', '')))
            words = set(target.split())
            if (target.replace(' ', '') in text.replace(' ', '') or
                    len(words) > 3 and len(words & set(text.split())) / len(words) >= .7):
                leads.append({'title': str(hit['title'])[:500], 'url': url})
    return papers, leads


def supplement_article(row, session):
    """Known article only. Preserve source/date; never bypass unknown publication dates."""
    from .daily import is_article, paper_links
    if not is_article(row) or (row.get('source') == 'embodied' and row.get('date_inferred')):
        return None
    page = session.fetch(row['source_url'])
    body = markdown_text(page.get('content'))
    if len(body.strip()) < 200 or any(t in body[:1500] for t in ('请完成验证', '环境异常', '访问过于频繁', 'Just a moment', 'Access Denied')):
        return None
    # Bounded text, from the known source URL only; the existing AI filter treats it as untrusted.
    return {**row, 'body': body[:50000], 'links_unavailable': False, 'body_source': 'deepseek_fetch'}, paper_links(body[:50000])
