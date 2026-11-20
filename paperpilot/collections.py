"""Explicit reading queue; temporary recommendations never imply a preference."""
import hashlib
from datetime import datetime, timezone
from . import store, daily


def key(paper):
    from .discovery import arxiv_id
    import re
    url = paper.get('paper_url') or paper.get('source_url') or paper['id']
    try:
        url = 'https://arxiv.org/abs/' + re.sub(r'v\d+$', '', arxiv_id(url))
    except ValueError:
        pass
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def resolve(origin, run_id, paper_id, *, allow_favorite=False):
    """Resolve a card from server-owned results shared by favorites and translation."""
    # Resolve trusted server records; clients cannot inject arbitrary URLs or cards.
    if origin == 'daily':
        rows = daily.cached()['items']
    elif origin == 'discovery':
        rows = store.get('discovery', run_id)['recommendations']
    elif origin == 'hotspot-recovered':
        rows = store.get('hotspot_recovered', run_id)['items']
    elif origin == 'hotspot-skipped':
        entry = store.get('hotspot_skip', run_id)
        rows = [entry['item']] if entry['kind'] == 'paper' else []
    elif origin == 'embodied-daily':
        rows = store.get('embodied_listing', run_id)['items']
    elif origin == 'hf-listing':
        rows = store.get('hf_listing', run_id)['items']
    elif origin == 'title-search':
        rows = store.get('title_search', run_id)['items']
    elif origin == 'model-recommendation':
        rows = store.get('model_recommendation', run_id)['items']
    elif origin == 'favorite' and allow_favorite:
        rows = [f['paper'] for f in store.all_objects('favorite')]
    else:
        raise ValueError('未知论文来源')
    return next((p for p in rows if p['id'] == paper_id), None)


def save(origin, run_id, paper_id):
    paper = resolve(origin, run_id, paper_id)
    if paper is None:
        raise ValueError('结果已更新，请刷新论文列表后加入待读清单')
    ident = key(paper)
    with store.LOCK:
        try:
            value = store.get('favorite', ident)
            value.pop('archived', None)
        except ValueError:
            value = {'id': ident, 'paper': paper, 'created_at': datetime.now(timezone.utc).isoformat()}
        return store.save('favorite', value)


def change(ident, action):
    if action != 'delete':
        raise ValueError('未知待读清单操作')
    with store.LOCK:
        store.get('favorite', ident)
        store.remove('favorite', ident)
        return {'ok': True}


def migrate():
    """Return all legacy archived candidates to the reading queue, without data loss."""
    import json
    with store.LOCK, store.connect() as db:
        for ident, body in db.execute("SELECT id,body FROM objects WHERE kind='favorite'").fetchall():
            value = json.loads(body)
            if 'archived' in value:
                value.pop('archived')
                db.execute("UPDATE objects SET body=? WHERE kind='favorite' AND id=?",
                           (json.dumps(value, ensure_ascii=False), ident))


def apply_metadata(paper, item):
    """Retain source identity at import time, independently of report generation."""
    from . import publication, news_metadata
    if item.get('kind') == 'news':
        return paper
    if not news_metadata.unresolved(item) and (news_metadata.unresolved(paper) or not paper.get('original_title') and not paper.get('report')):
        paper.update(title=item['title'].strip(), original_title=item['title'].strip(), title_source='论文来源元信息')
    for field in ('abstract', 'authors'):
        if not paper.get(field) and item.get(field):
            paper[field] = item[field]
    if not paper.get('publication_month') and paper.get('publication_date_source') != '手动填写':
        month = (item.get('published') or '')[:7]
        if month:
            try:
                publication.validate_month(month)
                paper.update(publication_month=month, publication_date_source='论文来源元信息')
            except ValueError:
                pass
    from . import paper_abstracts
    if paper.get('id'):
        paper_abstracts.prepare(paper)
    return publication.apply(paper)


def finish_import(favorite, paper_id):
    with store.LOCK:
        paper = store.get('paper', paper_id)
        item = favorite['paper']
        if not paper.get('source_url'):
            paper['source_url'] = item.get('paper_url') or item.get('source_url', '')
        apply_metadata(paper, item)
        store.save('paper', paper)
        # Only consume the snapshot selected by the user, never a replacement entry.
        try:
            current = store.get('favorite', favorite['id'])
            if current.get('created_at') == favorite.get('created_at'):
                store.remove('favorite', favorite['id'])
        except ValueError:
            pass
        return paper
