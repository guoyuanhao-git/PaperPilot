import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import credentials, store, providers


class PlatformCredentials(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        patcher = patch.object(credentials, 'CACHE', {})
        patcher.start(); self.addCleanup(patcher.stop)

    def scope(self, user):
        return store.scope({'id':user, 'directory':self.root/user})

    def test_windows_persistence_isolation_reset_and_mask(self):
        with patch('paperpilot.credentials.sys.platform', 'win32'), patch('paperpilot.keychain.Keychain') as keychain:
            with self.scope('alice'):
                credentials.save('sk-test1-private-abcd')
                credentials.CACHE.clear()
                self.assertEqual(credentials.get(), 'sk-test1-private-abcd')
                data = json.loads(credentials.path().read_text())
                self.assertEqual(data['deepseek_key'], credentials.get())
                self.assertEqual(credentials.storage_kind(), 'file')
                self.assertNotIn('private', providers.mask_key(credentials.get()))
            with self.scope('bob'):
                self.assertEqual(credentials.get(), '')
                credentials.save('sk-test2-private-efgh')
            with self.scope('alice'):
                credentials.delete(); credentials.CACHE.clear()
                self.assertEqual(credentials.get(), '')
                self.assertFalse(credentials.path().exists())
            with self.scope('bob'):
                self.assertEqual(credentials.get(), 'sk-test2-private-efgh')
            keychain.assert_not_called()

    def test_macos_keeps_keychain_and_never_writes_file(self):
        with self.scope('alice'), patch('paperpilot.credentials.sys.platform', 'darwin'), patch('paperpilot.keychain.Keychain') as keychain:
            keychain.return_value.execute.return_value = 'fixture'
            self.assertEqual(credentials.get(), 'fixture')
            credentials.save('new-fixture')
            credentials.delete()
            self.assertEqual([c.args[0] for c in keychain.return_value.execute.call_args_list], ['read','save','delete'])
            self.assertFalse(credentials.path().exists())
            keychain.return_value.execute.side_effect = ValueError('locked')
            with self.assertRaises(ValueError): credentials.save('fail-fixture')
            self.assertFalse(credentials.path().exists())
            self.assertEqual(credentials.get(), '')

    def test_failed_atomic_write_keeps_previous_key(self):
        with self.scope('alice'), patch('paperpilot.credentials.sys.platform', 'win32'):
            credentials.save('old-fixture')
            with patch('paperpilot.credentials.os.replace', side_effect=OSError('disk full')):
                with self.assertRaises(ValueError): credentials.save('new-fixture')
            credentials.CACHE.clear()
            self.assertEqual(credentials.get(), 'old-fixture')
            self.assertEqual(list(store.data_dir().glob('.credentials-*')), [])
