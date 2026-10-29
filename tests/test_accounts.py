import json
import os
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from paperpilot import accounts, store, credentials, providers, codex_account, user_profile
from paperpilot.server import Handler, TOKEN


class Accounts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.patches = [patch.object(store, 'DATA', self.root), patch.object(accounts, 'ROOT', None),
                        patch.object(accounts, 'REVISION', 'test-session'), patch.object(credentials, 'CACHE', {}),
                        patch.object(credentials, 'backend', return_value='')]
        for p in self.patches: p.start()

    def tearDown(self):
        for p in reversed(self.patches): p.stop()
        self.temp.cleanup()

    def create(self, name):
        accounts.create(name)
        return accounts.entry()

    def test_only_one_service_can_own_a_data_root(self):
        with accounts.instance_lock():
            with self.assertRaises(SystemExit):
                with accounts.instance_lock(): pass
        with accounts.instance_lock(): pass

    def test_empty_onboarding_and_user_storage_memory_credentials_isolation(self):
        accounts.initialize()
        self.assertIsNone(accounts.entry())
        a = self.create('alice')
        with store.scope(accounts.binding(a)):
            user_profile.save({'school': 'Private A'})
            for kind in ('paper', 'favorite', 'memory_event', 'assistant_memory', 'knowledge', 'job', 'recommendation_chat'):
                store.save(kind, {'id':'same', 'secret':'A'})
            credentials.save('key-A')
            first_name = credentials.service_name()
        b = self.create('bob')
        with store.scope(accounts.binding(b)), patch.dict(os.environ, {'DEEPSEEK_API_KEY':'external-secret'}):
            self.assertEqual(user_profile.get()['school'], '')
            for kind in ('paper', 'favorite', 'memory_event', 'assistant_memory', 'knowledge', 'job', 'recommendation_chat'):
                self.assertEqual(store.all_objects(kind), [])
            self.assertEqual(providers.api_key('deepseek'), '')
            self.assertNotEqual(first_name, credentials.service_name())
            self.assertFalse(store.settings()['memory']['enabled'])
        accounts.switch(a['id'])
        with store.scope(accounts.binding(accounts.entry())):
            self.assertEqual(user_profile.get()['school'], 'Private A')
            self.assertEqual(credentials.get(), 'key-A')

    def test_migration_preserves_paper_files_and_credential_namespace(self):
        store.init()
        user_profile.save({'school':'Original'})
        # A real document subtree including exports is moved, not regenerated.
        paper = self.root/'papers'/'a';paper.mkdir(parents=True)
        (paper/'source.pdf').write_bytes(b'pdf-original')
        old_service = credentials.service_name()
        with patch.object(store, 'ROOT', self.root/'framework'):
            accounts.initialize(legacy_name='legacy-user')
        first = accounts.entry()
        self.assertEqual(first['name'], 'legacy-user')
        with store.scope(accounts.binding(first)):
            self.assertEqual(user_profile.get()['school'], 'Original')
            self.assertEqual(credentials.service_name(), old_service)
            self.assertEqual((store.data_dir()/'papers/a/source.pdf').read_bytes(), b'pdf-original')
        self.assertFalse((self.root/'paperpilot.sqlite').exists())
        accounts.initialize()
        self.assertEqual(accounts.entry()['id'], first['id'])

    def test_pending_work_retains_user_and_blocks_deletion(self):
        accounts.initialize(); a = self.create('alice'); b = self.create('bob')
        release = threading.Event()
        with ThreadPoolExecutor(1) as pool:
            with store.scope(accounts.binding(a)):
                future = store.submit(pool, lambda: (release.wait(3), store.save('memory_event', {'id':'async','text':'alice'})))
            try:
                with self.assertRaisesRegex(ValueError, '后台任务'): accounts.delete(a['id'], a['name'])
                accounts.switch(b['id'])
            finally:
                release.set();future.result(timeout=5)
        with store.scope(accounts.binding(a)):
            self.assertEqual(store.get('memory_event','async')['text'],'alice')
        with store.scope(accounts.binding(b)):
            self.assertEqual(store.all_objects('memory_event'),[])
        accounts.delete(a['id'],a['name'])
        self.assertFalse(accounts.folder(a['id']).exists())
        self.assertTrue(accounts.folder(b['id']).exists())

    def test_codex_uses_own_home_and_never_inherits_api_auth(self):
        accounts.initialize();a=self.create('alice');b=self.create('bob')
        with patch.dict(os.environ, {'CODEX_HOME':'/old/home','OPENAI_API_KEY':'secret','CODEX_API_KEY':'secret'}):
            homes=[]
            for user in (a,b):
                with store.scope(accounts.binding(user)):
                    env=codex_account.environment();homes.append(env['CODEX_HOME'])
                    self.assertNotIn('OPENAI_API_KEY',env)
                    self.assertNotIn('CODEX_API_KEY',env)
                    self.assertIn('forced_login_method="chatgpt"',codex_account.auth_options())
                    self.assertIn(user['name'],codex_account.setup()['command'])
            self.assertNotEqual(*homes)
            self.assertNotIn('/old/home',homes)

    def test_http_stale_tabs_and_files_do_not_cross_users(self):
        accounts.initialize();a=self.create('alice')
        old=accounts.public()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        base=f'http://127.0.0.1:{server.server_port}'
        headers={'X-PaperPilot-Token':TOKEN,'X-PaperPilot-User':a['id'],'X-PaperPilot-Revision':old['revision']}
        try:
            with urllib.request.urlopen(base+'/api/bootstrap') as r: self.assertEqual(json.load(r)['accounts']['active'],a['id'])
            b=self.create('bob')
            for path,body in [('/api/profile-display', {'display_name':'leak','gender':''}),('/api/bootstrap',None),('/files/'+'a'*20+'/source.pdf?user='+a['id']+'&session='+old['revision'],None)]:
                req=urllib.request.Request(base+path, json.dumps(body).encode() if body else None,headers)
                with self.assertRaises(urllib.error.HTTPError) as error: urllib.request.urlopen(req)
                self.assertEqual(error.exception.code,409)
            with store.scope(accounts.binding(b)): self.assertEqual(user_profile.get()['display_name'],'')
        finally:
            server.shutdown();server.server_close()
