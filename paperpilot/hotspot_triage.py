"""Per-account browsing decisions, independent of research taste and reading state."""
import hashlib
import re
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.parse import urlsplit, urlunsplit
from . import collections, daily, store


def browsing_day(moment):
    return (moment.astimezone(ZoneInfo('Asia/Shanghai')) - timedelta(hours=8)).date().isoformat()


def today():
    return browsing_day(datetime.now(timezone.utc))


def entry_day(entry):
    if entry.get('day'):
        return entry['day']
    try:
        return browsing_day(datetime.fromisoformat(entry['created_at']))
    except (ValueError, KeyError, TypeError):
        return ''


def public():
    current = today()
    with store.LOCK:
        for kind in ('hotspot_skip', 'hotspot_recovered'):
            for entry in store.all_objects(kind):
                if entry_day(entry) != current:
                    store.remove(kind, entry['id'])
        return [{**entry, 'day': current} for entry in store.all_objects('hotspot_skip')]


def identity(item, kind):
    url = str(item.get('paper_url') or item.get('source_url') or item.get('id') or '')
    if kind == 'paper':
        match = re.search(r'(?:arxiv\.org/(?:abs|pdf)/|huggingface\.co/papers/|papers\.cool/arxiv/)(\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})(?:v\d+)?', url, re.I)
        if match:
            return 'paper:arxiv:' + match[1].lower()
        if re.search(r'https?://(?:dx\.)?doi\.org/', url, re.I):
            return 'paper:doi:' + re.sub(r'^https?://(?:dx\.)?doi\.org/', '', url, flags=re.I).lower()
    parts = urlsplit(url)
    return kind + ':' + urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ''))


def skip(body):
    public()
    origin = body.get('origin')
    if origin == 'news-article':
        item = next((a for a in daily.cached().get('articles', []) if a.get('source_url') == body.get('url')), None)
        kind = 'article'
    elif origin in ('daily', 'hf-listing', 'embodied-daily'):
        item = collections.resolve(origin, body.get('run_id', ''), body.get('paper_id'))
        kind = 'paper'
    else:
        raise ValueError('仅支持略过热点发现中的推文和论文')
    if not item:
        raise ValueError('列表已更新，请刷新后再试')
    key = identity(item, kind)
    # Keep a server-owned snapshot so old entries remain recoverable after the feed expires.
    value = {'id': hashlib.sha256(key.encode()).hexdigest()[:24], 'identity': key,
             'kind': kind, 'item': item, 'day': today(), 'created_at': datetime.now(timezone.utc).isoformat()}
    return store.save('hotspot_skip', value)


def restore(ident):
    with store.LOCK:
        public()
        value = store.get('hotspot_skip', ident)
        # Retain the card for waiting-list imports and abstract translation after feed expiry.
        if value['kind'] == 'paper':
            store.save('hotspot_recovered', {'id': ident, 'items': [value['item']], 'day': today()})
        store.remove('hotspot_skip', ident)
    return value
