"""Local desktop entry point. Does not depend on the Codex UI being open."""
import argparse
import hashlib
import json
import os
import secrets
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from . import store

PORT = 8765


def identity():
    return hashlib.sha256((str(store.ROOT.resolve()) + '\n' + str(store.DATA.resolve())).encode()).hexdigest()


def health(port=PORT):
    try:
        # A local probe must not use HTTP_PROXY from the shell environment.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=1) as response:
            value = json.load(response)
        return value if isinstance(value, dict) and value.get('app') == 'PaperPilot' else None
    except (OSError, ValueError):
        return None


def show(port):
    webbrowser.open(f'http://127.0.0.1:{port}/')


def start(port=PORT):
    existing = health(port)
    if existing:
        if existing.get('instance') != identity():
            raise ValueError('此端口运行着另一个 PaperPilot 项目，请先停止它，再打开本项目。')
        show(port)
        return
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise ValueError(f'端口 {port} 已被占用，无法启动。请先关闭占用此端口的旧服务。')
    runtime = store.DATA / 'desktop'
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = runtime / 'service.log'
    # Rotate a bounded log; all runtime files stay outside the distributable code.
    if log.exists() and log.stat().st_size > 2_000_000:
        log.replace(runtime / 'service.previous.log')
    nonce = secrets.token_hex(24)
    with log.open('a') as output:
        log.chmod(0o600)
        process = subprocess.Popen([sys.executable, '-m', 'paperpilot.server', '--port', str(port)],
                                   cwd=store.ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                   start_new_session=True, env={**os.environ, 'PAPERPILOT_DESKTOP_NONCE': nonce})
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        current = health(port)
        if current and current.get('instance') == identity() and current.get('desktop_nonce') == nonce:
            state = runtime / 'process.json'
            state.write_text(json.dumps({'pid':process.pid, 'port':port, 'nonce':nonce}))
            state.chmod(0o600)
            show(port)
            return
        if process.poll() is not None:
            raise ValueError(f'启动失败，请查看项目 data/desktop/service.log。可能已有服务正在其他端口运行。')
        time.sleep(.25)
    process.terminate()
    raise ValueError('启动超时，请查看项目 data/desktop/service.log。')


def stop():
    path = store.DATA / 'desktop/process.json'
    if not path.exists():
        raise ValueError('没有通过图标启动的服务记录；从终端启动的服务请在原终端停止。')
    saved = json.loads(path.read_text())
    current = health(saved['port'])
    if not current:
        path.unlink(missing_ok=True)
        return
    if (current.get('instance') != identity() or current.get('desktop_nonce') != saved['nonce']
            or current.get('pid') != saved['pid']):
        raise ValueError('服务已变化，未停止其他进程。')
    if current.get('busy'):
        raise ValueError('还有生成或后台整理任务正在运行，请完成后再停止 PaperPilot。')
    os.kill(saved['pid'], signal.SIGTERM)
    for _ in range(50):
        current = health(saved['port'])
        if not current or current.get('desktop_nonce') != saved['nonce']:
            path.unlink(missing_ok=True)
            return
        time.sleep(.1)
    raise ValueError('服务正在退出，请稍后重试停止操作。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stop', action='store_true')
    parser.add_argument('--port', type=int, default=PORT)
    args = parser.parse_args()
    # Serialize double clicks without locking the long-running server itself.
    from .file_lock import file_lock
    store.DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    with file_lock(store.DATA / 'desktop-launch.lock'):
        try:
            stop() if args.stop else start(args.port)
        except (OSError, ValueError) as error:
            print(str(error), file=sys.stderr)
            raise SystemExit(1) from None


if __name__ == '__main__':
    main()
