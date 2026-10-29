"""One-time local setup for coding harnesses; no access to their private key stores."""
import argparse
import getpass
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
import urllib.error
import urllib.request
from . import codex_account, providers, store


def project_location(directory, windows=False):
    # Quote the actual installation path for the shell shown in the setup guide.
    directory = str(directory)
    command = ("Set-Location -LiteralPath '" + directory.replace("'", "''") + "'"
               if windows else 'cd -- ' + shlex.quote(directory))
    return {'project_directory': directory, 'enter_project_command': command,
            'shell_label': 'PowerShell' if windows else '终端（sh / bash / zsh）'}


def public(port):
    account = (store.account() or {}).get('id', '')
    capabilities = providers.capabilities(store.settings())
    commands = {}
    for provider in ('codex', 'deepseek'):
        args = (['python', '-m', 'paperpilot.model_setup'] if os.name == 'nt' else ['./run.sh', '--connect-model'])
        args += [provider, '--account', account, '--port', str(port)]
        commands[provider] = subprocess.list2cmdline(args) if os.name == 'nt' else shlex.join(args)
    return {**project_location(store.ROOT.resolve(), os.name == 'nt'),
            'account_id': account, 'local_url': f'http://127.0.0.1:{port}/',
            'commands': commands, 'codex_available': bool(shutil.which('codex')),
            'codex_binary': shutil.which('codex'),
            'deepseek_configured': capabilities['keys']['deepseek'], 'capabilities': capabilities,
            # Only a home path is returned, never the cached login or API key.
            'codex_home': str(store.data_dir() / 'codex') if codex_account.isolated()
                          else os.environ.get('CODEX_HOME', str(Path.home() / '.codex')),
            'codex_isolated': codex_account.isolated()}


class LocalClient:
    def __init__(self, port, account):
        self.url = f'http://127.0.0.1:{port}'
        self.account = account
        self.headers = {}
        session = self.call('/api/session')
        if session.get('active') != account:
            raise ValueError('当前用户已切换。请回到设置页，为目标用户重新复制接入说明。')
        self.headers = {'X-PaperPilot-User': account, 'X-PaperPilot-Revision': session['revision']}
        setup = self.call('/api/model-setup')
        self.headers['X-PaperPilot-Token'] = setup['token']
        self.setup = setup

    def call(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data,
                                     headers={**self.headers, 'Content-Type': 'application/json'})
        try:
            # Loopback setup must never forward credentials through an HTTP proxy.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(req, timeout=25) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                raise ValueError('用户会话已改变，请重新复制接入说明。') from None
            raise ValueError(f'本地接入请求未完成（HTTP {exc.code}），请在设置页检查。') from None
        except (OSError, ValueError):
            raise ValueError('无法连接 PaperPilot，请先启动应用并保持设置页中的用户不变。') from None
        if result.get('error'):
            raise ValueError('本地接入请求未完成，请在设置页检查。')
        return result


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        raise ValueError('本地接入不接受重定向')


def connect(client, provider, from_env=False):
    if provider == 'codex':
        status = client.call('/api/codex-status')
        if not status['ready']:
            binary = client.setup.get('codex_binary') or shutil.which('codex')
            if not binary:
                raise ValueError('未找到 Codex CLI，请先安装 Codex CLI 后重试。')
            env = dict(os.environ)
            for name in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN'):
                env.pop(name, None)
            env['CODEX_HOME'] = client.setup['codex_home']
            options = ['-c', 'forced_login_method="chatgpt"']
            if client.setup['codex_isolated']:
                options += ['-c', 'cli_auth_credentials_store="file"']
            # The official CLI owns browser authorization and refresh; no token copying.
            if subprocess.call([binary, *options, 'login'], env=env) != 0:
                raise ValueError('Codex 登录未完成；原配置保留。')
            if not client.call('/api/codex-status')['ready']:
                raise ValueError('尚未确认 Codex 订阅登录，请在设置页检查。')
    elif provider == 'deepseek':
        if not client.setup['deepseek_configured']:
            if from_env:
                key = os.environ.get('DEEPSEEK_API_KEY', '')
                if not key:
                    raise ValueError('当前终端未配置 DEEPSEEK_API_KEY；可在 PaperPilot 手动配置中输入。')
            else:
                if not sys.stdin.isatty():
                    raise ValueError('请在交互终端输入密钥，或使用 --key-from-env；不要把密钥写入命令或对话。')
                key = getpass.getpass('DeepSeek API Key（输入不回显）：').strip()
            from .credentials import valid_key
            valid_key(key)
            client.call('/api/deepseek-key', {'action': 'confirm', 'key': key})
            key = ''
    else:
        raise ValueError('未知模型服务')
    client.call('/api/settings', {'provider': provider})


def main(argv=None):
    parser = argparse.ArgumentParser(description='为当前 PaperPilot 用户完成一次模型接入')
    parser.add_argument('provider', choices=('codex', 'deepseek'))
    parser.add_argument('--account', required=True, help='设置页提供的用户 ID')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--key-from-env', action='store_true', help='显式将当前终端的 DEEPSEEK_API_KEY 保存给指定用户')
    parser.add_argument('--check', action='store_true', help='仅检查本地配置，不保存、不调用模型')
    parser.add_argument('--test', action='store_true', help='接入后发送一条简短连接测试')
    args = parser.parse_args(argv)
    if not re.fullmatch(r'[a-f0-9]{32}', args.account) or not 1 <= args.port <= 65535:
        parser.error('请使用设置页生成的有效用户 ID 和端口')
    try:
        client = LocalClient(args.port, args.account)
        if args.check:
            ready = client.call('/api/codex-status')['ready'] if args.provider == 'codex' else client.setup['deepseek_configured']
            print('已配置；实际模型权限可在页面测试连接。' if ready else '尚未配置。')
            return 0 if ready else 1
        connect(client, args.provider, args.key_from_env)
        print('接入配置已保存。回到 PaperPilot 点击“检查接入”即可更新状态。')
        if args.test:
            job = client.call('/api/test-provider', {})
            deadline = time.monotonic() + 480
            while time.monotonic() < deadline:
                result = client.call('/api/job/' + job['id'])
                if result['status'] in ('completed', 'failed', 'cancelled'):
                    if result['status'] != 'completed':
                        raise ValueError('连接测试未成功，请在 PaperPilot 查看任务结果；接入配置已保留。')
                    print('模型连接测试成功。')
                    return 0
                time.sleep(1)
            raise ValueError('连接测试仍在后台执行，请在 PaperPilot 查看。')
        return 0
    except (ValueError, KeyboardInterrupt, EOFError) as exc:
        print(str(exc) if isinstance(exc, ValueError) else '接入已取消。', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
