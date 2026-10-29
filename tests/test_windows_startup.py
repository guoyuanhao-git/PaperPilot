"""Windows entrypoint integration; only temporary source copies and accounts."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
import urllib.request


@unittest.skipUnless(os.name == 'nt', 'Windows CMD entrypoints')
class WindowsStartup(unittest.TestCase):
    def test_entrypoints_restart_persistence_and_port_conflict(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='paperpilot-win-') as tmp:
            root = Path(tmp) / '中文 project space'
            root.mkdir()
            for folder in ('paperpilot', 'web'):
                shutil.copytree(source / folder, root / folder, ignore=shutil.ignore_patterns('__pycache__'))
            for name in ('run.cmd', '启动 PaperPilot.cmd', '停止 PaperPilot.cmd'):
                shutil.copy2(source / name, root / name)
            asset = Path('node_modules/katex/dist/katex.min.js')
            (root / asset).parent.mkdir(parents=True)
            shutil.copy2(source / asset, root / asset)
            data = root / '测试 data'
            env = {**os.environ, 'PAPERPILOT_DATA': str(data), 'PAPERPILOT_PYTHON': sys.executable, 'PYTHONUTF8': '1'}
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def call(name, extra=''):
                result = subprocess.run(f'cmd.exe /d /c ""{root / name}" --port {port} {extra}"', cwd=root, env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=110)
                return result
            def get(path):
                with opener.open(f'http://127.0.0.1:{port}{path}', timeout=5) as response:
                    return json.load(response)
            try:
                result = call('启动 PaperPilot.cmd')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                first = get('/api/health')
                state = json.loads((data / 'desktop/process.json').read_text(encoding='utf-8'))
                self.assertEqual(state['pid'], first['pid'])
                result = call('启动 PaperPilot.cmd')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(get('/api/health')['pid'], first['pid'])
                with opener.open(f'http://127.0.0.1:{port}/', timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn(b'PaperPilot', response.read())
                bootstrap = get('/api/bootstrap')
                headers = {'Content-Type': 'application/json', 'X-PaperPilot-Token': bootstrap['token'], 'X-PaperPilot-User': '', 'X-PaperPilot-Revision': bootstrap['accounts']['revision']}
                request = urllib.request.Request(f'http://127.0.0.1:{port}/api/accounts/create', data=json.dumps({'name': 'synthetic_test'}).encode(), headers=headers)
                with opener.open(request, timeout=10) as response:
                    account = json.load(response)
                result = call('停止 PaperPilot.cmd')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertFalse((data / 'desktop/process.json').exists())
                result = call('启动 PaperPilot.cmd')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(get('/api/session')['active'], account['active'])
                result = call('停止 PaperPilot.cmd')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                with socket.socket() as occupied:
                    occupied.bind(('127.0.0.1', port))
                    occupied.listen()
                    result = call('run.cmd')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('端口', result.stderr)
            finally:
                if (data / 'desktop/process.json').exists():
                    result = call('run.cmd', '--stop')
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
