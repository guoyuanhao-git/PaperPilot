"""Use Codex's own login flow; never copy another workspace's credentials."""
import os
import shlex
import shutil
import subprocess
from . import store


def isolated():
    return (store.account() or {}).get('codex_mode') == 'isolated'


def environment():
    result = dict(os.environ)
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'):
        result.pop(key, None)
    if isolated():
        home = store.data_dir() / 'codex'
        home.mkdir(exist_ok=True, mode=0o700)
        result['CODEX_HOME'] = str(home)
    return result


def auth_options():
    return ['-c', 'cli_auth_credentials_store="file"', '-c', 'forced_login_method="chatgpt"'] if isolated() else []


def setup():
    user = store.account()
    arguments = ['./run.sh', '--codex-login', user['name']] if user else ['codex', 'login']
    if user and store.DATA != (store.ROOT / 'data').resolve():
        arguments = ['env', 'PAPERPILOT_DATA=' + str(store.DATA), *arguments]
    command = shlex.join(arguments)
    return {'command': command, 'isolated': isolated()}


def status():
    binary = shutil.which('codex')
    if not binary:
        return {'ready': False, 'message': '未找到 Codex CLI，请先安装。'}
    try:
        result = subprocess.run([binary, *auth_options(), 'login', 'status'], env=environment(),
                                capture_output=True, text=True, timeout=15)
        logged = result.returncode == 0 and 'chatgpt' in (result.stdout + result.stderr).lower()
        return {'ready': logged, 'message': '已通过 ChatGPT 订阅登录；模型权限以测试连接为准。' if logged else '尚未通过 ChatGPT 订阅登录，请执行下方配置命令。'}
    except subprocess.TimeoutExpired:
        return {'ready': False, 'message': '检查超时，请稍后重试。'}


def login(name):
    from . import accounts
    accounts.ROOT = store.DATA
    if not (accounts.ROOT / 'accounts.json').exists():
        raise SystemExit('请先启动 PaperPilot，在页面中创建用户。')
    user = next((u for u in accounts.registry()['users'] if u['name'] == name), None)
    if not user:
        raise SystemExit('用户不存在，请先在 PaperPilot 中创建。')
    binary = shutil.which('codex')
    if not binary:
        raise SystemExit('未找到 Codex CLI，请先安装。')
    with store.scope(accounts.binding(user)):
        raise SystemExit(subprocess.call([binary, *auth_options(), 'login'], env=environment()))
