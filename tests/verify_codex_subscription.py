"""Isolated subscription acceptance. No credentials are copied or printed."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def prepare():
    folder = Path(tempfile.mkdtemp(prefix='paperpilot-codex-')) / '中文 subscription test'
    folder.mkdir()
    data = folder / 'data'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {**os.environ, 'PAPERPILOT_DATA': str(data), 'PYTHONUTF8': '1'}
    log = folder / 'service.log'
    with log.open('wb') as output:
        process = subprocess.Popen([sys.executable, '-X', 'utf8', str(Path(__file__).resolve()), '--serve', str(data), '--port', str(port)], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    url = f'http://127.0.0.1:{port}'
    def get(path):
        with opener.open(url + path, timeout=3) as response:
            return json.load(response)
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Test service exited; inspect its local service.log')
        try:
            bootstrap = get('/api/bootstrap')
            break
        except OSError:
            time.sleep(.1)
    else:
        process.terminate()
        raise RuntimeError('Test service startup timeout')
    headers = {'Content-Type':'application/json', 'X-PaperPilot-Token':bootstrap['token'], 'X-PaperPilot-User':'', 'X-PaperPilot-Revision':bootstrap['accounts']['revision']}
    req = urllib.request.Request(url + '/api/accounts/create', data=b'{"name":"subscription_test"}', headers=headers)
    with opener.open(req, timeout=10) as response:
        account = json.load(response)
    from paperpilot.model_setup import LocalClient
    client = LocalClient(port, account['active'])
    status = client.call('/api/codex-status')
    state = {'data':str(data),'port':port,'account':account['active'],'service_pid':get('/api/health')['pid'],'wrapper_pid':process.pid,'count':0}
    state_path = folder / 'acceptance-state.json'
    state_path.write_text(json.dumps(state), encoding='utf-8')
    print(json.dumps({'state_file':str(state_path),'login_ready':status['ready'],'message':status['message'],'setup_command':client.setup['commands']['codex']},ensure_ascii=False),flush=True)


def serve(data, port):
    os.environ['PAPERPILOT_DATA'] = data
    from paperpilot import cancellation
    import threading
    lock = threading.Lock()
    attempts = Path(data).parent / 'model-attempts.json'
    original = cancellation.run_process
    def counted(command, **kwargs):
        if 'exec' in command:
            with lock:
                count = json.loads(attempts.read_text(encoding='utf-8'))['count'] if attempts.exists() else 0
                if count >= 20:
                    raise ValueError('Acceptance budget exhausted (20 requests)')
                attempts.write_text(json.dumps({'count':count+1}), encoding='utf-8')
            command = list(command)
            command[-1:-1] = ['-c', 'model_providers.paperpilot-http.request_max_retries=0',
                              '-c', 'model_providers.paperpilot-http.stream_max_retries=0']
        return original(command, **kwargs)
    cancellation.run_process = counted
    from paperpilot import server
    with server.accounts.instance_lock():
        server.serve(port)


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--prepare',action='store_true')
    parser.add_argument('--serve')
    parser.add_argument('--port',type=int)
    args=parser.parse_args()
    if args.prepare: prepare()
    elif args.serve: serve(args.serve,args.port)
    else: parser.error('Choose --prepare or --serve')
