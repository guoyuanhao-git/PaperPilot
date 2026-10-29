import contextlib
import io
import json
import os
import shlex
import tempfile
import threading
from http.server import ThreadingHTTPServer
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import model_setup, store


class Client:
    def __init__(self, ready=False):
        self.setup = {'deepseek_configured': ready, 'codex_home':'/isolated/test-codex', 'codex_isolated':True}
        self.calls = []
        self.logged = ready

    def call(self, path, body=None):
        self.calls.append((path, body))
        return {'ready': self.logged} if path == '/api/codex-status' else {}


class ModelSetup(unittest.TestCase):
    def test_existing_key_not_replaced_and_only_provider_changed(self):
        client=Client(True)
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'different-secret'}):
            model_setup.connect(client,'deepseek',True)
        self.assertEqual(client.calls,[('/api/settings',{'provider':'deepseek'})])

    def test_explicit_environment_import_no_secret_in_stdout(self):
        client=Client()
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY':'fixture-secret'}), contextlib.redirect_stdout(io.StringIO()) as output:
            model_setup.connect(client,'deepseek',True)
        self.assertEqual(client.calls[0],('/api/deepseek-key',{'action':'confirm','key':'fixture-secret'}))
        self.assertNotIn('fixture-secret',output.getvalue())
        self.assertEqual(client.calls[1],('/api/settings',{'provider':'deepseek'}))

    def test_missing_key_and_noninteractive_do_not_mutate(self):
        for envmode in (True,False):
            client=Client()
            with patch.dict(os.environ,{},clear=True),patch('sys.stdin.isatty',return_value=False):
                with self.assertRaises(ValueError): model_setup.connect(client,'deepseek',envmode)
            self.assertEqual(client.calls,[])

    def test_codex_keeps_account_home_and_drops_inherited_api_auth(self):
        client=Client()
        def login(args,env):
            self.assertEqual(env['CODEX_HOME'],'/isolated/test-codex')
            self.assertNotIn('OPENAI_API_KEY',env)
            self.assertNotIn('CODEX_ACCESS_TOKEN',env)
            self.assertEqual(args[-1],'login')
            client.logged=True
            return 0
        with patch.dict(os.environ,{'OPENAI_API_KEY':'secret','CODEX_ACCESS_TOKEN':'secret'}),patch('shutil.which',return_value='/bin/codex'),patch('subprocess.call',side_effect=login):
            model_setup.connect(client,'codex')
        self.assertEqual(client.calls[-1],('/api/settings',{'provider':'codex'}))

    def test_failed_login_never_switches_provider(self):
        client=Client()
        with patch('shutil.which',return_value='/bin/codex'),patch('subprocess.call',return_value=1):
            with self.assertRaises(ValueError):model_setup.connect(client,'codex')
        self.assertFalse(any(path=='/api/settings' for path,_ in client.calls))

    def test_wrong_account_stops_before_getting_setup(self):
        with patch.object(model_setup.LocalClient,'call',return_value={'active':'b','revision':'r'}) as call:
            with self.assertRaisesRegex(ValueError,'用户已切换'): model_setup.LocalClient(8765,'a')
            self.assertEqual(call.call_count,1)

    def test_generated_command_is_account_bound_without_names_or_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            with store.scope({'id':'a'*32,'name':'private-name','directory':Path(directory),'codex_mode':'isolated'}),patch.object(model_setup.providers,'capabilities',return_value={'keys':{'deepseek':True}}):
                store.init()
                result=model_setup.public(12345)
                command=result['commands']['deepseek']
                self.assertIn('--account '+ 'a'*32,command)
                self.assertIn('--port 12345',command)
                self.assertNotIn('private-name',command)
                self.assertTrue(result['codex_isolated'])
                self.assertEqual(result['project_directory'],str(store.ROOT.resolve()))
                self.assertEqual(result['account_id'],'a'*32)
                self.assertEqual(result['local_url'],'http://127.0.0.1:12345/')

    def test_project_path_is_dynamic_and_shell_quoted(self):
        path = "/tmp/Researcher's Project/$(literal) `name`"
        result = model_setup.project_location(path)
        self.assertEqual(result['project_directory'], path)
        self.assertEqual(shlex.split(result['enter_project_command']), ['cd', '--', path])
        windows = model_setup.project_location("C:\\Work\\Researcher's Project", True)
        self.assertEqual(windows['enter_project_command'], "Set-Location -LiteralPath 'C:\\Work\\Researcher''s Project'")
        self.assertEqual(windows['shell_label'], 'PowerShell')

    def test_local_client_never_follows_redirects(self):
        with self.assertRaises(ValueError): model_setup.NoRedirect().redirect_request(None,None,302,'',{},'https://other.invalid')


class LocalSetupIntegration(unittest.TestCase):
    def test_live_setup_is_scoped_and_key_is_available_without_restart(self):
        from paperpilot import accounts, credentials, providers
        from paperpilot.server import Handler
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            with patch.object(store,'DATA',root),patch.object(accounts,'ROOT',None),patch.object(accounts,'REVISION','test-model-session'),patch.object(credentials,'CACHE',{}),patch('paperpilot.credentials.sys.platform','linux'),patch.object(providers,'KEYS',{}):
                accounts.initialize();accounts.create('setup-test-a');a=accounts.entry()
                server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    client=model_setup.LocalClient(server.server_port,a['id'])
                    self.assertFalse(client.setup['deepseek_configured'])
                    with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'sk-test-only-connection'}):
                        model_setup.connect(client,'deepseek',True)
                    state=client.call('/api/model-setup')
                    self.assertTrue(state['deepseek_configured'])
                    self.assertNotIn('sk-test-only-connection',json.dumps(state))
                    with store.scope(accounts.binding(a)):
                        self.assertEqual(store.settings()['provider'],'deepseek')
                        self.assertEqual(credentials.get(),'sk-test-only-connection')
                    accounts.create('setup-test-b');b=accounts.entry()
                    with self.assertRaises(ValueError):client.call('/api/settings',{'provider':'codex'})
                    with store.scope(accounts.binding(b)):
                        self.assertFalse(credentials.get())
                        self.assertEqual(store.settings()['provider'],'codex')
                    with store.scope(accounts.binding(a)):
                        self.assertEqual(store.settings()['provider'],'deepseek')
                finally:
                    server.shutdown();server.server_close();thread.join()
