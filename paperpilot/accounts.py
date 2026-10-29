"""Local workspaces, isolated by immutable IDs. This is not remote authentication."""
import json
import re
import secrets
import shutil
import threading
import uuid
from pathlib import Path
from contextlib import contextmanager
from . import store

LOCK = threading.RLock()
ROOT = None
REVISION = secrets.token_hex(16)


def enabled():
    return ROOT is not None


def registry():
    if ROOT is None:
        return {'users': [], 'active': None}
    return json.loads((ROOT / 'accounts.json').read_text())


def save_registry(value):
    path = ROOT / 'accounts.json'
    temporary = ROOT / ('accounts-' + uuid.uuid4().hex + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.chmod(0o600)
    temporary.replace(path)


def folder(ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('无效用户 ID')
    return ROOT / 'users' / ident


def entry(ident=None):
    data = registry()
    ident = data['active'] if ident is None else ident
    return next((u for u in data['users'] if u['id'] == ident), None)


def binding(user):
    return {**user, 'directory': folder(user['id'])}


def public():
    data = registry()
    return {'enabled': enabled(), 'active': data['active'], 'revision': REVISION,
            'users': [{k: u[k] for k in ('id', 'name')} for u in data['users']]}


def initialize(root=None, legacy_name="default"):
    """Resumable migration runs before the HTTP server starts."""
    global ROOT
    ROOT = Path(root or store.DATA).resolve()
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)
    if not (ROOT / 'accounts.json').exists():
        legacy = (ROOT / 'paperpilot.sqlite').exists()
        users = []
        if legacy:
            import hashlib
            users = [{'id': uuid.uuid4().hex, 'name': validate_name(legacy_name), 'codex_mode': 'existing',
                      'allow_environment_key': True,
                      'credential_service': 'PaperPilot.DeepSeek.' + hashlib.sha256(str(ROOT).encode()).hexdigest()[:20]}]
        save_registry({'version': 1, 'active': users[0]['id'] if users else None, 'users': users, 'migration_pending': legacy})
    data = registry()
    if data.get('migration_pending'):
        user = data['users'][0]
        target = folder(user['id'])
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        for path in list(ROOT.iterdir()):
            if path.name in ('accounts.json', 'users') or path.name.startswith('accounts-'):
                continue
            destination = target / path.name
            if destination.exists():
                raise ValueError('旧数据迁移遇到同名文件，请检查备份后再启动')
            shutil.move(str(path), str(destination))
        # Keep originals untouched; only the first account can read copies of its reference material.
        references = store.ROOT / '论文重写参考'
        if references.exists() and not (target / 'references').exists():
            shutil.copytree(references, target / 'references')
        data['migration_pending'] = False
        save_registry(data)
    from . import library, paper_identity, assistant_memory, documents, collections, style_samples, paper_storage
    for user in data['users']:
        with store.scope(binding(user)):
            store.init()
            paper_storage.recover()
            collections.migrate()
            style_samples.migrate()
            library.migrate()
            paper_identity.migrate()
            assistant_memory.recover()
            documents.upgrade_library_figures()


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[\w\-\u4e00-\u9fff]{1,40}', name.strip()):
        raise ValueError('用户名须为 1–40 个字母、数字、中文、下划线或短横线')
    return name.strip()


def create(name):
    global REVISION
    name = validate_name(name)
    with LOCK:
        data = registry()
        if any(u['name'].casefold() == name.casefold() for u in data['users']):
            raise ValueError('用户名已存在')
        user = {'id': uuid.uuid4().hex, 'name': name, 'codex_mode': 'isolated', 'allow_environment_key': False}
        folder(user['id']).mkdir(parents=True, mode=0o700)
        with store.scope(binding(user)):
            store.init()
        data['users'].append(user)
        data['active'] = user['id']
        save_registry(data)
        REVISION = secrets.token_hex(16)
        return public()


def switch(ident):
    global REVISION
    with LOCK:
        if not entry(ident):
            raise ValueError('用户不存在')
        data = registry()
        data['active'] = ident
        save_registry(data)
        REVISION = secrets.token_hex(16)
        return public()


def delete(ident, name):
    global REVISION
    from . import credentials
    with LOCK:
        user = entry(ident)
        if not user or name != user['name']:
            raise ValueError('请输入要删除的完整用户名')
        with store.LOCK:
            if store.TASKS.get(str(folder(ident)), 0):
                raise ValueError('该用户仍有后台任务，请完成后再删除')
        with store.scope(binding(user)):
            credentials.delete()
            from .providers import KEYS
            KEYS.pop(str(store.data_dir()) + ':deepseek', None)
        # Rename first so old paths cannot be recreated by requests, then remove the owned subtree.
        trash = ROOT / 'users' / ('deleted-' + uuid.uuid4().hex)
        folder(ident).rename(trash)
        data = registry()
        data['users'] = [u for u in data['users'] if u['id'] != ident]
        if data['active'] == ident:
            data['active'] = data['users'][0]['id'] if data['users'] else None
        save_registry(data)
        REVISION = secrets.token_hex(16)
        shutil.rmtree(trash)
        return public()


def reference_dir():
    return store.data_dir() / 'references'


@contextmanager
def instance_lock():
    """Only one service may own a data root, including its background jobs."""
    from .file_lock import file_lock
    store.DATA.mkdir(parents=True, exist_ok=True)
    from contextlib import ExitStack
    with ExitStack() as stack:
        try:
            stack.enter_context(file_lock(store.DATA / 'accounts-instance.lock', blocking=False))
        except BlockingIOError:
            raise SystemExit('此数据目录的 PaperPilot 已在运行，请使用已有页面或设置独立 PAPERPILOT_DATA。') from None
        yield
