import json
import os
import sqlite3
import threading
from contextvars import ContextVar, copy_context
from contextlib import contextmanager
from pathlib import Path
from . import reasoning

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('PAPERPILOT_DATA', ROOT / 'data')).resolve()
LOCK = threading.RLock()
SCOPE = ContextVar('paperpilot_user', default=None)
TASKS = {}


def data_dir():
    context = SCOPE.get()
    return context['directory'] if context else DATA


def account():
    return SCOPE.get()


@contextmanager
def scope(value):
    token = SCOPE.set(value)
    try:
        yield
    finally:
        SCOPE.reset(token)


def submit(executor, function, *args):
    """Background jobs retain the requesting user's storage and credential scope."""
    context, directory = copy_context(), str(data_dir())
    with LOCK:
        TASKS[directory] = TASKS.get(directory, 0) + 1
    def run():
        try:
            return context.run(function, *args)
        finally:
            with LOCK:
                TASKS[directory] -= 1
    try:
        return executor.submit(run)
    except BaseException:
        with LOCK:
            TASKS[directory] -= 1
        raise


DEFAULTS = {
    'reasoning': dict(reasoning.DEFAULTS),
    'reasoning_policy': reasoning.default_policy(),
    'provider': 'codex', 'model': '', 'vision': True,
    'codex_reasoning_effort': 'high', 'codex_detail_reasoning_effort': 'high',
    'deepseek': {'base_url': 'https://api.deepseek.com', 'model': 'deepseek-flash', 'thinking': 'low',
                 'detail_model': 'deepseek-flash', 'detail_thinking': 'high'},
    'math_style_mode': 'cached',
    'memory': {'enabled': False}, 'knowledge_deep_thinking': False,
    'hotspot_news_enabled': True,
    'web_supplement_enabled': False,
    'discovery_sources': ['arxiv'],
    'context_chars': 100000, 'output_tokens': 8192, 'output_tokens_auto': True,
    'schedule': {'enabled': False, 'interval_days': 2, 'query': '', 'next_run': None, 'sources': ['arxiv'], 'count': 2},
}


def init():
    data_dir().mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS objects (kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))')
        db.execute('CREATE TABLE IF NOT EXISTS config (id INTEGER PRIMARY KEY, body TEXT)')
    for j in all_objects('job'):
        if j['status'] in ('running', 'queued'):
            j.update(status='failed', error='应用重启，中断了上次任务。可以重新运行。')
            save('job', j)


@contextmanager
def connect():
    db = sqlite3.connect(data_dir() / 'paperpilot.sqlite', timeout=30)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        with db:
            yield db
    finally:
        db.close()


def save(kind, value):
    with LOCK, connect() as db:
        db.execute('INSERT OR REPLACE INTO objects VALUES (?,?,?)', (kind, value['id'], json.dumps(value, ensure_ascii=False)))
    return value


def get(kind, ident):
    with connect() as db:
        row = db.execute('SELECT body FROM objects WHERE kind=? AND id=?', (kind, ident)).fetchone()
    if not row:
        raise ValueError('找不到这条记录')
    return json.loads(row[0])


def all_objects(kind, limit=None):
    query = 'SELECT body FROM objects WHERE kind=? ORDER BY rowid DESC'
    params = [kind]
    if limit is not None:
        if type(limit) is not int or limit < 0:
            raise ValueError('记录数量上限应为非负整数')
        query += ' LIMIT ?'
        params.append(limit)
    with connect() as db:
        rows = db.execute(query, params).fetchall()
    return [json.loads(r[0]) for r in rows]


def remove(kind, ident):
    with LOCK, connect() as db:
        db.execute('DELETE FROM objects WHERE kind=? AND id=?', (kind, ident))


def settings():
    with connect() as db:
        row = db.execute('SELECT body FROM config WHERE id=1').fetchone()
    saved = json.loads(row[0]) if row else {}
    result = json.loads(json.dumps(DEFAULTS))
    for key, value in saved.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    result.pop('openai', None)
    result['reasoning_policy'] = reasoning.migrate(saved)
    result['reasoning'] = reasoning.effective(result)  # Read-only effective task policy.
    result['knowledge_deep_thinking'] = result['reasoning']['knowledge'] == 'high'
    # Keyword recommendations are now explicitly requested; retain legacy fields only for migration.
    result['schedule']['enabled'] = False
    result['schedule']['next_run'] = None
    if result['provider'] not in ('codex', 'deepseek'):
        result['provider'] = 'codex'
    result['discovery_sources'] = [s for s in result['discovery_sources'] if s in ('arxiv', 'huggingface', 'papers_cool')] or ['arxiv']
    result['schedule']['sources'] = [s for s in result['schedule']['sources'] if s in ('arxiv', 'huggingface', 'papers_cool')] or ['arxiv']
    return result


def save_settings(value):
    with LOCK, connect() as db:
        db.execute('INSERT OR REPLACE INTO config VALUES (1,?)', (json.dumps(value, ensure_ascii=False),))


def profile():
    from .user_profile import context
    return context()


def save_profile(value):
    from .user_profile import save
    return save(value)


def feedback_context():
    entries = []
    for p in all_objects('paper') + all_objects('reading_history'):
        if p.get('feedback'):
            entries.append({'title': p['title'], 'feedback': p['feedback'], 'read_status': p.get('read_status')})
    return json.dumps(entries[:30], ensure_ascii=False)
