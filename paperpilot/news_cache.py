"""Account-local, three-day news evidence cache; no model decisions live here."""
import hashlib
import json
from . import store

VERSION = 1


def fingerprint(row):
    return hashlib.sha256(json.dumps({k: row.get(k) for k in
        ('source', 'source_url', 'feed_url', 'channel', 'title', 'published', 'body', 'excerpt')},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Cache:
    def __init__(self, sources, now):
        from .daily import recent
        self.now = now
        try:
            value = store.get('news_evidence', 'current')
        except ValueError:
            value = {}
        if value.get('version') != VERSION:
            value = {}
        selected = set(sources['selected'])
        custom = {r['id']: r['url'] for r in sources['custom']}
        def allowed(row):
            return (row.get('source') in selected and recent(row.get('published'), now)
                    and (row['source'] not in custom or row.get('feed_url') == custom[row['source']]))
        self.listings = {s: {**entry, 'rows': [r for r in entry['rows'] if allowed(r)]}
                         for s, entry in value.get('listings', {}).items() if s in selected}
        self.bodies = {k: e for k, e in value.get('bodies', {}).items() if allowed(e['row'])}
        self.reused = 0

    def since(self, source):
        from .daily import LOCAL_ZONE, stamp, window_start
        entry = self.listings.get(source, {})
        checked = stamp(entry.get('full_checked'))
        if checked and checked.astimezone(LOCAL_ZONE).date() == self.now.astimezone(LOCAL_ZONE).date():
            return self.now.astimezone(LOCAL_ZONE).replace(hour=0, minute=0, second=0, microsecond=0)
        return window_start(self.now)

    def merge(self, source, rows):
        from .daily import recent, window_start
        old = self.listings.get(source, {})
        combined = {r['source_url']: r for r in old.get('rows', [])}
        combined.update({r['source_url']: r for r in rows if recent(r.get('published'), self.now)})
        full = self.now.isoformat() if self.since(source) == window_start(self.now) else old.get('full_checked')
        rows = list(combined.values())
        self.listings[source] = {'rows': rows, 'full_checked': full}
        return rows

    def body(self, original, web_enabled=False):
        from .daily import stamp
        entry = self.bodies.get(fingerprint(original))
        if not entry:
            return None
        # Failed reads can recover; enabling supplemental Fetch gets an immediate retry.
        if entry['row'].get('links_unavailable'):
            checked = stamp(entry.get('checked'))
            if (not checked or (self.now-checked).total_seconds() >= 3600
                    or web_enabled != entry.get('web_enabled', False)):
                return None
        self.reused += 1
        return entry['row'], entry['links']

    def remember(self, original, row, links, web_enabled=False):
        row = dict(row)
        # Bound cached evidence and retain all extracted paper links separately.
        for field in ('body', 'excerpt'):
            if isinstance(row.get(field), str): row[field] = row[field][:150000]
        self.bodies[fingerprint(original)] = {'row': row, 'links': links,
            'checked': self.now.isoformat(), 'web_enabled': web_enabled}

    def save(self):
        store.save('news_evidence', {'id': 'current', 'version': VERSION,
            'listings': self.listings, 'bodies': self.bodies})
