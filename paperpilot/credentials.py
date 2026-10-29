"""Per-user credentials: macOS Keychain; local plaintext file on other platforms."""
import hashlib
import json
import os
import sys
import tempfile
import threading
from pathlib import Path
from . import store

LOCK = threading.RLock()
CACHE = {}


def service_name():
    # Preserve existing per-user Keychain namespaces.
    return (store.account() or {}).get('credential_service') or 'PaperPilot.DeepSeek.' + hashlib.sha256(str(store.data_dir()).encode()).hexdigest()[:20]


def path():
    return store.data_dir() / 'credentials.json'


def valid_key(key, empty=False):
    if not isinstance(key, str) or len(key) > 4096 or (not key and not empty) or any(c.isspace() for c in key):
        raise ValueError('API Key 不能为空、含空白或超过 4096 字符')
    return key


def read_file():
    try:
        file = path()
        if file.is_symlink():
            raise ValueError('凭据文件不能是符号链接')
        if not file.exists():
            return None
        value = json.loads(file.read_text())
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('本地凭据文件格式无效')
        valid_key(value.get('deepseek_key'), empty=True)
        return value
    except (OSError, ValueError):
        raise ValueError('无法读取当前用户的本地凭据文件，请检查权限或重置密钥') from None


def write_file(key):
    valid_key(key, empty=True)
    directory = store.data_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name != 'nt':
        directory.chmod(0o700)
    name = None
    try:
        fd, name = tempfile.mkstemp(prefix='.credentials-', suffix='.tmp', dir=directory)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'version':1, 'deepseek_key':key}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path())
    except OSError:
        raise ValueError('本地密钥保存失败，请检查当前用户目录权限；已有密钥保留') from None
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def storage_kind():
    return 'keychain' if sys.platform == 'darwin' else 'file'


def backend(action, service, key=None):
    if sys.platform == 'darwin':
        from .keychain import Keychain
        # Do not fall back to plaintext if Keychain is locked or unavailable.
        return Keychain().execute(action, service, key)
    if action == 'read':
        value = read_file()
        return value['deepseek_key'] if value else ''
    if action == 'save':
        write_file(key)
    elif action == 'delete':
        path().unlink(missing_ok=True)
    else:
        raise ValueError('未知密钥操作')
    return ''


def get():
    with LOCK:
        name = service_name()
        if name not in CACHE:
            CACHE[name] = backend('read', name)
        return CACHE[name]


def save(key):
    valid_key(key)
    with LOCK:
        name = service_name()
        backend('save', name, key)
        CACHE[name] = key


def delete():
    with LOCK:
        name = service_name()
        backend('delete', name)
        CACHE[name] = ''
