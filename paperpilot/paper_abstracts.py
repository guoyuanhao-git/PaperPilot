"""An import-time abstract, with translations keyed to the exact source text."""
import copy
import hashlib
from . import documents, store, report_cache

VERSION = 2


def translation_key(source):
    return hashlib.sha256(('zh\0' + source).encode()).hexdigest()


def prepare(paper):
    """Local-only: prefer imported metadata and never recycle an unchecked report excerpt."""
    saved = paper.get('abstract_record') or {}
    metadata = paper.get('abstract')
    metadata = metadata.strip() if isinstance(metadata, str) and 40 <= len(metadata.strip()) <= 20000 else ''
    revision = paper.get('pdf_sha256') or paper['id']
    if (saved.get('version') == VERSION and saved.get('pdf_revision') == revision
            and (not metadata or saved.get('original') == metadata)):
        result = copy.deepcopy(saved)
    else:
        result = documents.abstract_source(paper)
        result.update(version=VERSION, pdf_revision=revision)
    original = result.get('original', '')
    if original and not result.get('translation'):
        previous = (paper.get('report') or {}).get('abstract') or {}
        if previous.get('original') == original and previous.get('translation'):
            result.update(translation=previous['translation'], fetched_at=previous.get('fetched_at') or (paper.get('report') or {}).get('generated_at') or report_cache.now())
        else:
            try:
                cached = store.get('abstract_translation', translation_key(original))
                if cached.get('source_text') == original and cached.get('text'):
                    result.update(translation=cached['text'], fetched_at=cached.get('created_at', report_cache.now()))
            except ValueError:
                pass
    paper['abstract_record'] = result
    return copy.deepcopy(result)


def save_translation(paper, abstract):
    """Keep a successful translation even if later report stages fail."""
    from .service import SAVE_LOCK
    with SAVE_LOCK:
        current = store.get('paper', paper['id'])
        latest = prepare(current)
        if latest.get('original') != abstract.get('original') or latest.get('pdf_revision') != abstract.get('pdf_revision'):
            raise ValueError('摘要原文已改变，请重新生成解读')
        current['abstract_record'] = copy.deepcopy(abstract)
        store.save('paper', current)
        if abstract.get('original') and abstract.get('translation'):
            store.save('abstract_translation', {
                'id': translation_key(abstract['original']), 'source_text': abstract['original'],
                'language': 'zh', 'text': abstract['translation'], 'created_at': abstract.get('fetched_at', report_cache.now()),
                'provider': 'paper_report', 'model': ''})
