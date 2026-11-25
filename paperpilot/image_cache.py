"""Bound reproducible page/crop images; never evict a report's only copy.

All operations run under documents.PDF_LOCK. Consumers must read/copy their
image before trimming, rather than hold an evictable path across model calls.
The budget is per account, shared by all papers, and excludes preserved images.
"""
import json
import re

from . import store

LIMIT_BYTES = 512 * 1024 * 1024
IMAGE_NAME = re.compile(r'(?:crop-[a-f0-9]{16}|page-\d+)\.png')


def trim():
    from .documents import PDF_LOCK, directory
    with PDF_LOCK:
        # Fetch only storage metadata, not thousands of full reading reports.
        with store.connect() as db:
            rows = db.execute("""SELECT id, json_extract(body, '$.pdf_released'),
                json_extract(body, '$.report.figures'), json_extract(body, '$.translation.figures') FROM objects WHERE kind='paper'""").fetchall()
        entries = []
        for ident, released, figures, translated_figures in rows:
            folder = directory(ident)
            if (released or not (folder / 'source.pdf').is_file()
                    or (folder / '.release-staging').exists()
                    or (folder / '.restore-staging').exists()):
                continue
            pinned = {f.get('image_file') for f in json.loads(figures or '[]') + json.loads(translated_figures or '[]')}
            for path in folder.iterdir():
                if not IMAGE_NAME.fullmatch(path.name) or path.name in pinned or path.is_symlink():
                    continue
                try:
                    stat = path.stat()
                    entries.append((stat.st_mtime_ns, path, stat.st_size))
                except FileNotFoundError:
                    pass
        total = sum(size for _, _, size in entries)
        for _, path, size in sorted(entries):
            if total <= LIMIT_BYTES:
                break
            try:
                path.unlink(missing_ok=True)
                total -= size
            except OSError:
                pass  # A locked file may be removable on the next pass (Windows).
        return total
