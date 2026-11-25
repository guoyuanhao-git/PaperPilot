"""Independent, non-sliding freshness for static parts of a paper report."""
import copy
from datetime import datetime, timedelta, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


def recent(paper, key, at=None):
    report = paper.get('report') or {}
    value = report.get(key)
    if key == 'paper_info' and paper.get('paper_info_revision') and paper.get('paper_info_revision') == (paper.get('pdf_sha256') or paper.get('id')):
        value = paper.get('paper_info') or value
    if not isinstance(value, dict):
        return None
    if key == 'abstract' and not (value.get('original') and value.get('translation') and isinstance(value.get('pages'), list)):
        return None
    if key == 'paper_info' and not (value.get('original_title') and isinstance(value.get('authors'), list)):
        return None
    # Legacy reports inherit their original generation date exactly once. Never
    # derive freshness from subsequent report regeneration or manual edits.
    stamp = value.get('fetched_at', report.get('generated_at'))
    try:
        fetched = datetime.fromisoformat(stamp)
        if fetched.tzinfo is None:
            return None
        age = (at or datetime.now(timezone.utc)) - fetched
        if not timedelta(0) <= age <= timedelta(days=7):
            return None
    except (TypeError, ValueError):
        return None
    cached = copy.deepcopy(value)
    cached['fetched_at'] = stamp
    return cached
