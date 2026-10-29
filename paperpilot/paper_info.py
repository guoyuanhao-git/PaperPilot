"""Source-grounded author roles, organizations and verified scholarly metadata."""
import json
import re
import urllib.parse
from . import documents, scholarly_metadata, author_names, report_cache
from .schemas import obj


def schema():
    string = {'type': 'string'}
    return obj({'original_title': string, 'authors': {'type': 'array', 'items': obj({'name': string, 'affiliations': {'type': 'array', 'items': string}, 'emails': {'type':'array','items':string}, 'corresponding':{'type':'boolean'}, 'corresponding_evidence':string})},
                'organizations':{'type':'array','items':string}, 'project_url': string, 'code_url': string})


def source_material(paper):
    pages = json.loads((documents.directory(paper['id']) / 'pages.json').read_text())
    text = '\n'.join(p['text'] for p in pages)
    urls = set(re.findall(r'https?://[^\s<>\)\]}]+', text))
    # PDF links often wrap across lines; use actual URI annotations as well.
    from pypdf import PdfReader
    for page in PdfReader(documents.directory(paper['id']) / 'source.pdf').pages:
        for ref in page.get('/Annots', []):
            annot = ref.get_object()
            action = annot.get('/A', {})
            if hasattr(action, 'get_object'): action = action.get_object()
            uri = action.get('/URI', '')
            if isinstance(uri, str) and uri.startswith(('https://', 'http://')):
                urls.add(uri)
    urls = sorted(u.rstrip('.,;。') for u in urls if safe_url(u))
    return text, urls


def safe_url(url):
    try:
        p = urllib.parse.urlsplit(url)
        return p.scheme in ('http', 'https') and bool(p.hostname) and not p.username and not p.password
    except ValueError:
        return False


def norm(value):
    return re.sub(r'[^\w]', '', value.casefold())


def apply_defaults(info, paper=None):
    """Display policy is separate from explicitly evidenced author roles."""
    authors = info.get('authors') or []
    # A sole author is not automatically a designated corresponding author.
    # Also undo this inference in already-saved reports without a model call.
    if len(authors) == 1 and authors[0].get('corresponding_source') == 'last_author_default':
        authors[0].update(corresponding=False, corresponding_evidence='')
        authors[0].pop('corresponding_source', None)
    if len(authors) > 1 and not any(a.get('corresponding') for a in authors):
        if 'corresponding_mentioned' not in info:
            # Old reports lack the explicit-presence marker. Check local text;
            # reading a saved report must never trigger a network/model call.
            try:
                pages = json.loads((documents.directory(paper['id']) / 'pages.json').read_text())
                text = '\n'.join(p['text'] for p in pages)
                info['corresponding_mentioned'] = bool(re.search(r'corresponding\s*author|通讯作者', text, re.I))
            except (KeyError, TypeError, OSError, ValueError):
                info['corresponding_mentioned'] = None
        if info.get('corresponding_mentioned') is False:
            authors[-1].update(corresponding=True, corresponding_source='last_author_default')
    overrides = (paper or {}).get('author_citations', {})
    for author in authors:
        author.pop('manual_citation', None)
        value = overrides.get(norm(author['name']))
        if value:
            author['manual_citation'] = dict(value)
    return author_names.enrich(info)


def citation_authors(info):
    return [a for i, a in enumerate(info.get('authors', [])) if i == 0 or a.get('corresponding')]


def set_citations(paper, values):
    info = (paper.get('report') or {}).get('paper_info')
    if not info or not isinstance(values, dict):
        raise ValueError('请先整理论文相关信息')
    apply_defaults(info, paper)
    allowed = {norm(a['name']) for a in citation_authors(info)}
    if any(norm(k) not in allowed for k in values):
        raise ValueError('引用量只能填写当前一作或通讯作者')
    updated = dict(paper.get('author_citations', {}))
    for name, count in values.items():
        key = norm(name)
        if count is None:
            updated.pop(key, None)
        elif type(count) is int and 0 <= count <= 999999999:
            updated[key] = {'count': count, 'source': 'manual', 'updated_at': report_cache.now()}
        else:
            raise ValueError('引用量应为非负整数，留空则移除手填值')
    paper['author_citations'] = updated
    apply_defaults(info, paper)
    paper['exports'] = []
    return paper


def extract(paper, invoke):
    text, urls = source_material(paper)
    prompt = ('仅从原论文提取身份信息，不翻译或改写论文标题。authors 按原文署名顺序列出，每位作者的 affiliations 仅填本文署名单位。'
              'PDF 提取常会丢失空格：name、affiliations、organizations 需恢复人名与英文单词间的正常空格（如 FirstnameLastname → Firstname Lastname），但不翻译、不更换姓名与机构；证据片段仍保留原文。'
              'organizations 按论文署名顺序去重列出所有组织，不只是第一作者和通讯作者的单位。emails 只填能明确归属该作者的原文邮箱。'
              'corresponding 仅在原文明确标为通讯作者时为 true，并在 corresponding_evidence 逐字引用带该作者名字和标记的原文片段；不要把末位作者、项目负责人或共同一作默认当通讯。证据不足为 false，evidence 为空。'
              '不要把参考文献作者当作本文作者。缺失字段用空字符串或空数组；不能根据常识补全。'
              'project_url 为本文项目主页，code_url 为本文官方代码仓库，只能从给定链接中选择，不使用参考文献项目。不要猜测引用量。'
              '\n原文首页与后续页：\n' + text[:18000] + '\n原文实际链接：' + json.dumps(urls, ensure_ascii=False))
    info = invoke('整理作者、单位与项目链接', prompt, schema())['value']
    if not isinstance(info, dict) or not isinstance(info.get('original_title'), str) or not isinstance(info.get('authors'), list):
        raise ValueError('论文相关信息格式无效')
    grounded = norm(text)
    title = info['original_title'].strip()
    if not title or norm(title) not in grounded:
        raise ValueError('无法在原文核对论文标题，未保存')
    authors = []
    for a in info['authors']:
        if not isinstance(a, dict) or not isinstance(a.get('name'), str) or not isinstance(a.get('affiliations'), list):
            raise ValueError('作者信息格式无效')
        if norm(a['name']) and norm(a['name']) in grounded:
            evidence=a.get('corresponding_evidence','')
            corresponding=(a.get('corresponding') is True and isinstance(evidence,str) and bool(norm(evidence)) and norm(evidence) in grounded and norm(a['name']) in norm(evidence) and bool(re.search(r'corresponding\s*author|通讯作者',text,re.I)))
            emails=[e for e in a.get('emails',[]) if isinstance(e,str) and re.fullmatch(r'[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}',e) and e.lower() in text.lower()]
            authors.append({'name': a['name'], 'affiliations': [v for v in a['affiliations'] if isinstance(v,str) and norm(v) and norm(v) in grounded], 'emails':emails,'corresponding':corresponding,'corresponding_evidence':evidence if corresponding else ''})
    result = {'original_title': title, 'authors': authors, 'source_url': paper.get('source_url', ''),
              'project_url': info.get('project_url') if info.get('project_url') in urls else '',
              'code_url': info.get('code_url') if info.get('code_url') in urls else '',
              'organizations':list(dict.fromkeys(v for v in info.get('organizations',[v for a in authors for v in a['affiliations']]) if isinstance(v,str) and norm(v) and norm(v) in grounded)), 'metadata_version':3,
              'corresponding_mentioned': bool(re.search(r'corresponding\s*author|通讯作者', text, re.I)),
              'fetched_at': report_cache.now()}
    apply_defaults(result, paper)
    for i, author in enumerate(authors):
        if i == 0 or author['corresponding']:
            chinese = author_names.resolve(author)
            if chinese:
                author['chinese_name'] = chinese
    result['venue'] = scholarly_metadata.venue(paper,result)
    return author_names.enrich(result)
