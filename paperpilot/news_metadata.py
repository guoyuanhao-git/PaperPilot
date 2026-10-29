"""Exact public identifiers to paper names; no model guesses or title search."""
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse, unquote
from . import discovery, store
from .classic_papers import CitationPage

MISSING_TITLE = '论文标题暂未获取'


def unresolved(paper):
    title = str(paper.get('title') or '').strip()
    return (not title or title == MISSING_TITLE or title.startswith(('arXiv ·', 'https://', 'http://'))
            or bool(re.fullmatch(r'(?:arXiv:)?\d{4}\.\d{4,5}(?:v\d+)?', title, re.I))
            or title.casefold() in ('untitled', 'anonymous', 'main', 'paper', 'document'))


def resolve(paper):
    url = paper.get('paper_url') or paper.get('source_url', '')
    parsed = urlparse(url)
    if parsed.hostname == 'arxiv.org':
        ident = re.sub(r'v\d+$', '', discovery.arxiv_id(url))
        page = CitationPage()
        page.feed(discovery.public_fetch('https://arxiv.org/abs/' + ident, {'arxiv.org'}))
        source_id = page.value('citation_arxiv_id')
        pdf = page.value('citation_pdf_url')
        if not source_id and pdf:
            source_id = discovery.arxiv_id(pdf.replace('http://', 'https://'))
        if re.sub(r'v\d+$', '', source_id.removeprefix('arXiv:')) != ident:
            raise ValueError('arXiv 页面标识不匹配')
        result = {'title': page.value('citation_title'), 'authors': page.meta.get('citation_author', []),
                  'abstract': page.value('citation_abstract'), 'metadata_source': 'arxiv.org'}
    elif parsed.hostname == 'doi.org' and re.fullmatch(r'/10\.\d{4,9}/\S+', parsed.path):
        doi = unquote(parsed.path[1:])
        value = json.loads(discovery.public_fetch('https://api.crossref.org/works/' + quote(doi, safe=''), {'api.crossref.org'})).get('message', {})
        if str(value.get('DOI', '')).casefold() != doi.casefold():
            raise ValueError('DOI 元信息标识不匹配')
        result = {'title': next(iter(value.get('title') or []), ''),
                  'authors': [' '.join(filter(None, (a.get('given'), a.get('family')))) for a in value.get('author', [])],
                  'abstract': discovery.clean_text(value.get('abstract') or ''), 'metadata_source': 'api.crossref.org'}
    else:
        raise ValueError('未接入该链接的元信息')
    result['title'] = ' '.join(result['title'].split())
    if not result['title'] or len(result['title']) > 2000 or unresolved(result):
        raise ValueError('没有可靠的论文标题')
    # A missing abstract must not erase evidence already obtained from another source.
    return {k: v for k, v in result.items() if v}


def enrich(papers, *, check=None):
    check = check or (lambda: None)
    papers = [dict(p) for p in papers]
    pending, cached = {}, {}
    now = time.time()
    for paper in papers:
        if not unresolved(paper):
            continue
        url = paper.get('paper_url') or paper.get('source_url', '')
        key = hashlib.sha256(url.encode()).hexdigest()
        try:
            entry = store.get('news_paper_metadata', key)
        except ValueError:
            entry = {}
        ttl = 7 * 86400 if entry.get('value') else 900
        if now - entry.get('fetched_at', 0) < ttl:
            cached[url] = entry.get('value') or {}
        else:
            pending[url] = (key, paper)
    def fetch(pair):
        url, (key, paper) = pair
        try:
            value = resolve(paper)
        except Exception:
            value = {}
        return url, key, value
    check()
    if pending:
        # Network workers do not access account state; cache writes stay in caller scope.
        with ThreadPoolExecutor(max_workers=2) as pool:
            for url, key, value in pool.map(fetch, pending.items()):
                check()
                cached[url] = value
                store.save('news_paper_metadata', {'id': key, 'fetched_at': now, 'value': value})
    for paper in papers:
        if unresolved(paper):
            value = cached.get(paper.get('paper_url') or paper.get('source_url', ''), {})
            if value:
                paper.update(value, metadata_status='resolved')
            else:
                paper.update(title=MISSING_TITLE, metadata_status='unavailable')
    return papers
