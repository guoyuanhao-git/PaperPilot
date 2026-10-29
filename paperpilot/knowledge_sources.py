"""Bounded, cached original-text evidence shared by both graph model providers."""
import hashlib
import json
import re
import time
import urllib.request
import urllib.parse
from html.parser import HTMLParser
from . import discovery, documents, store

VERSION = 4


def local_revision(paper):
    folder = documents.directory(paper['id'])
    current = [(p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None
               for p in (folder / 'pages.json', folder / 'source.pdf')]
    saved = paper.get('source_storage', {}).get('revision')
    if saved and current[0] and list(current[0]) == list(saved[0] or []):
        return [current[0], tuple(saved[1]) if saved[1] else None]
    return current


def cache_pdf(paper):
    """Explicit original download, isolated by account and removed with its paper."""
    from .service import SAVE_LOCK
    if paper.get('pdf_released'):
        raise ValueError('原文空间已主动释放，请在阅读页面恢复原文')
    target = documents.directory(paper['id']) / 'source.pdf'
    if target.exists():
        return False
    try:
        url = 'https://arxiv.org/pdf/' + discovery.arxiv_id(paper.get('source_url') or '')
    except ValueError:
        url = paper.get('pdf_url') or ''
    hosts = {'arxiv.org', 'www.arxiv.org', 'papers.nips.cc', 'proceedings.neurips.cc', 'openreview.net'}
    def check(value):
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.port not in (None, 443) or parsed.username or parsed.password:
            raise ValueError('暂无支持自动下载的原文地址，请上传 PDF')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            check(newurl)
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    check(url)
    with urllib.request.build_opener(Redirect()).open(urllib.request.Request(url, headers=discovery.UA), timeout=60) as response:
        data = response.read(100 * 1024 * 1024 + 1)
    if len(data) > 100 * 1024 * 1024 or not data.startswith(b'%PDF-'):
        raise ValueError('原文不是有效 PDF 或超过 100 MB')
    with SAVE_LOCK:
        live = store.get('paper', paper['id'])  # Do not resurrect a deleted paper.
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            return False
        temporary = target.with_suffix('.download')
        temporary.write_bytes(data)
        temporary.replace(target)
        live['pdf_cached'] = True
        store.save('paper', live)
    return True


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip, self.article = [], 0, False

    def handle_starttag(self, tag, attrs):
        if tag == 'article':
            self.article = True
        if tag in ('script', 'style', 'nav'):
            self.skip += 1
        if tag in ('p', 'div', 'section', 'li', 'h1', 'h2', 'h3', 'h4'):
            self.parts.append('\n\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'nav'):
            self.skip = max(0, self.skip - 1)
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4'):
            self.parts.append('\n\n')

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def paragraphs(text):
    result = []
    for part in re.split(r'\n\s*\n', text):
        part = ' '.join(part.split())
        # PDFs often yield an entire page as one paragraph. Do not discard dense
        # method pages; split at sentence/word boundaries with bounded excerpts.
        pending = ''
        for sentence in re.split(r'(?<=[.!?。！？])\s+', part):
            for chunk in re.findall(r'.{1,1800}(?:\s+|$)|\S{1,1800}', sentence):
                chunk = chunk.strip()
                if pending and len(pending) + len(chunk) > 1800:
                    result.append(pending)
                    pending = ''
                pending = (pending + ' ' + chunk).strip()
        if pending:
            result.append(pending)
    return result


def report_material(paper):
    report = paper.get('report') or {}
    parts = []
    for section in report.get('sections', []):
        if not isinstance(section, dict):
            continue
        for block in section.get('blocks') or [section]:
            if not isinstance(block, dict):
                continue
            parts.extend(p for p in block.get('paragraphs', []) if isinstance(p, str) and p.strip())
            for equation in block.get('equations', []):
                if isinstance(equation, dict):
                    parts.append(' '.join(str(equation.get(k) or '') for k in ('latex', 'meaning', 'implementation')).strip())
    return {'status': 'report', 'url': '', 'paragraphs': list(dict.fromkeys(parts))}


def introduction_material(text):
    """Locate an introduction, or explicitly label a bounded opening fallback."""
    start = re.search(r'(?im)^\s*(?:1[.\s]*)?(?:introduction|引言|绪论)\s*[:：]?\s*$', text)
    if start:
        rest = text[start.end():]
        end = re.search(r'(?im)^\s*(?:2[.\s]+[^\n]{2,100}|(?:related work|background|preliminaries|methods?|approach|相关工作|方法))\s*$', rest)
        selected = rest[:end.start()] if end else rest[:24000]
        return {'section': 'introduction', 'paragraphs': paragraphs(selected[:24000])}
    return {'section': 'opening', 'paragraphs': paragraphs(text[:16000])}


def reading_excerpts(material, paper, profile, budget=14000):
    """A report or introduction supplies the overview; original text supplies detail."""
    report = report_material(paper)
    overview_budget = min(8000, budget * 2 // 3)
    overview = select(report, profile, budget=overview_budget)
    if not overview:
        intro = material.get('introduction') or {'section': 'opening', 'paragraphs': material.get('paragraphs', [])[:8]}
        entry = {**material, **intro, 'prefix': 'intro' if intro['section']=='introduction' else 'opening', 'ordered': True}
        overview = select(entry, profile, budget=overview_budget)
    used = {e['text'] for e in overview}
    detail = {**material, 'paragraphs': [p if p not in used else '' for p in material.get('paragraphs', [])]}
    extra = select(detail, profile, budget=max(0, budget-sum(len(e['text']) for e in overview)))
    return overview + extra


def collect(paper):
    """Fetch only the paper's canonical arXiv HTML; never follow arbitrary model URLs.

    Local PDF text is preferred; otherwise fetch the canonical online original. Failures are
    cached for an hour, successes for a week; no pairwise repeated HTTP requests.
    """
    path = documents.directory(paper['id']) / 'pages.json'
    pdf = path.parent / 'source.pdf'
    stamp = local_revision(paper)
    key = hashlib.sha256(json.dumps([VERSION, paper.get('source_url'), stamp]).encode()).hexdigest()
    try:
        saved = store.get('knowledge_source', paper['id'])
    except ValueError:
        saved = {}
    ttl = 7 * 86400 if saved.get('status') in ('web', 'local') else 3600
    if saved.get('signature') == key and time.time() - saved.get('fetched_at', 0) < ttl:
        return saved
    result = {'id': paper['id'], 'signature': key, 'fetched_at': time.time(), 'status': 'unavailable', 'url': '', 'paragraphs': []}
    full_text = ''
    # Prefer the user's exact local paper version. It also avoids re-fetching available originals.
    if path.exists():
        try:
            pages = json.loads(path.read_text())
            full_text = '\n\n'.join(page.get('text', '') if isinstance(page, dict) else str(page) for page in pages)
            parts = []
            for page in pages:
                parts.extend(paragraphs(page.get('text', '') if isinstance(page, dict) else str(page)))
            if parts:
                result.update(status='local', paragraphs=parts)
        except (OSError, ValueError, TypeError):
            pass
    if not result['paragraphs'] and pdf.exists():
        try:
            from pypdf import PdfReader
            parts, size, texts = [], 0, []
            reader = PdfReader(pdf)
            for page in reader.pages[:250]:
                text = page.extract_text() or ''
                texts.append(text)
                parts.extend(paragraphs(text))
                size += len(text)
                if size >= 300000:
                    break
            if parts:
                full_text = '\n\n'.join(texts)
                result.update(status='local', paragraphs=parts)
        except Exception:
            # Malformed/scanned PDFs must not prevent an online original fallback.
            pass
    if not result['paragraphs']:
        try:
            ident = discovery.arxiv_id(paper.get('source_url') or '')
            url = 'https://arxiv.org/html/' + ident
            parser = ArticleText()
            parser.feed(discovery.public_fetch(url, {'arxiv.org', 'www.arxiv.org'}))
            parts = paragraphs(''.join(parser.parts))
            if parser.article and sum(map(len, parts)) > 2000:
                full_text = ''.join(parser.parts)
                result.update(status='web', url=url, paragraphs=parts)
        except (OSError, ValueError, UnicodeError):
            pass
    # Bound persisted text as well as the model input; no PDF downloads or extra files.
    result['paragraphs'] = result['paragraphs'][:1200]
    result['introduction'] = introduction_material(full_text)
    store.save('knowledge_source', result)
    return result


def select(material, profile, aliases=(), budget=14000):
    """Favor methods and current research terms; retain source slices, not generated facts."""
    query = set(re.findall(r'[a-z][a-z0-9-]{2,}|[\u4e00-\u9fff]{2,}', ' '.join(profile.values()).casefold()))
    method = re.compile(r'\b(method|architectur\w*|condition\w*|modulat\w*|layer|train\w*|policy|action|simulat\w*|algorithm|attention|loss|representation)\b', re.I)
    aliases = [re.compile(r'(?<!\w)' + re.escape(a.casefold()) + r'(?!\w)') for a in aliases if len(a) >= 3]
    candidates = []
    for i, part in enumerate(material.get('paragraphs', [])):
        # Reference entries alone don't establish use/inheritance. Keep substantive prose.
        if len(part) < (10 if material.get('status') == 'report' else 100) or len(part) > 6000 or (len(part) < 500 and re.match(r'^\[\d+\].*\b(19|20)\d{2}\b', part)):
            continue
        lower = part.casefold()
        score = len(set(method.findall(lower))) + 3 * sum(t in lower for t in query) + 5 * sum(bool(a.search(lower)) for a in aliases)
        candidates.append((score, i, part))
    chosen, used = [], 0
    ordering = (lambda row: row[1]) if material.get('ordered') else (lambda row: (-row[0], row[1]))
    for _, i, part in sorted(candidates, key=ordering):
        if used + len(part) <= budget:
            chosen.append((i, part))
            used += len(part)
    prefix = material.get('prefix') or ('report' if material.get('status') == 'report' else 'text')
    return [{'id': f'{prefix}:{i+1}', 'text': part, 'url': material.get('url', ''), 'kind': material.get('status', 'unavailable'),
             **({'section': material['section']} if material.get('section') else {})}
            for i, part in sorted(chosen)]
