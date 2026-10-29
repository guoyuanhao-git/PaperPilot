"""Mutually exclusive paper preferences, independent of reading state and history."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import store

LOCAL_ZONE = ZoneInfo('Asia/Shanghai')
COMPLETED = ('已速览', '已精读')


def now():
    return datetime.now(timezone.utc).isoformat()


def initialize(paper):
    """Migrate legacy manual labels without inventing reading completions."""
    if paper.get('reading_state_version') == 1:
        return paper
    source = store.data_dir() / 'papers' / paper['id'] / 'source.pdf'
    added = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat() if source.exists() else now()
    paper.setdefault('added_at', paper.get('created_at') or added)
    paper.setdefault('starred', paper.get('read_status') == '收藏')
    paper['read_status'] = '待阅读' if paper.get('report') else '未标记'
    paper['reading_completions'] = []
    paper['reading_session'] = 0
    paper['reading_state_version'] = 1
    return paper


def migrate():
    for paper in store.all_objects('paper'):
        if paper.get('reading_state_version') != 1:
            store.save('paper', initialize(paper))


def report_ready(paper):
    initialize(paper)
    paper['read_status'] = '待阅读'
    paper['reading_session'] = paper.get('reading_session', 0) + 1


def change(ident, action, report_at=None, starred=None, preference=None):
    # Serialize with generation, notes, deletion and other paper mutations.
    from .service import SAVE_LOCK
    with SAVE_LOCK:
        paper = initialize(store.get('paper', ident))
        if action == 'preference':
            if preference not in ('none', 'liked', 'starred'):
                raise ValueError('请选择喜欢、收藏或取消标记')
            if preference != 'none':
                from .paper_identity import validate
                validate(paper, required=True)
            paper.update(liked=preference == 'liked', starred=preference == 'starred')
        elif action == 'star':
            if not isinstance(starred, bool):
                raise ValueError('收藏状态无效')
            if starred:
                from .paper_identity import validate
                validate(paper, required=True)
            paper['starred'] = starred
            if starred:
                paper['liked'] = False
        elif action == 'start':
            if paper['read_status'] in COMPLETED:
                paper['reading_session'] += 1
                paper['read_status'] = '未标记'
        elif action == 'finish':
            report = paper.get('report') or {}
            if report.get('mode') not in ('overview', 'detailed', 'deep'):
                raise ValueError('请先生成论文解读')
            if not report_at or report_at != report.get('generated_at'):
                raise ValueError('解读已更新，请刷新后再标记阅读完毕')
            from .paper_identity import validate
            validate(paper, required=True)
            session = paper['reading_session']
            events = paper['reading_completions']
            if not any(e['session'] == session for e in events):
                events.append({'at': now(), 'mode': report['mode'], 'report_at': report_at, 'session': session})
            paper['read_status'] = '已速览' if report['mode'] == 'overview' else '已精读'
        else:
            raise ValueError('未知论文操作')
        return store.save('paper', paper)


def statistics(papers, at=None):
    current = (at or datetime.now(timezone.utc)).astimezone(LOCAL_ZONE)
    today = current.replace(hour=0, minute=0, second=0, microsecond=0)
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    counts = {'today': 0, 'week': 0}
    for paper in papers:
        times = []
        for event in paper.get('reading_completions', []):
            try:
                stamp = datetime.fromisoformat(event['at'])
                if stamp.tzinfo is not None:
                    times.append(stamp.astimezone(LOCAL_ZONE))
            except (ValueError, TypeError, KeyError):
                continue
        counts['today'] += any(today <= t <= current for t in times)
        counts['week'] += any(sunday <= t <= current for t in times)
    return counts
