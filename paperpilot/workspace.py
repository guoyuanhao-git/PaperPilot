"""Account-local navigation preferences, independent of model/task settings."""
from . import store

OPTIONAL_MODULES = ('knowledge', 'hotspots', 'conferences')


def current():
    try:
        value = store.get('workspace', 'navigation')
    except ValueError:
        value = {}
    return {'hidden_modules': [key for key in OPTIONAL_MODULES if key in value.get('hidden_modules', [])]}


def save(value):
    hidden = value.get('hidden_modules')
    if not isinstance(hidden, list) or any(key not in OPTIONAL_MODULES for key in hidden):
        raise ValueError('请选择有效的功能模块')
    store.save('workspace', {'id': 'navigation', 'hidden_modules': list(dict.fromkeys(hidden))})
    return current()
