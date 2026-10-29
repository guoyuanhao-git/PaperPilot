import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from paperpilot import store


class StoreConnection(unittest.TestCase):
    def test_commit_rollback_close_and_delete(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(store, 'DATA', Path(tmp)):
            store.init()
            with store.connect() as db:
                db.execute("INSERT INTO config VALUES (7, 'committed')")
            with self.assertRaises(sqlite3.ProgrammingError):
                db.execute('SELECT 1')
            with self.assertRaisesRegex(ValueError, 'rollback'):
                with store.connect() as failed:
                    failed.execute("UPDATE config SET body='uncommitted' WHERE id=7")
                    raise ValueError('rollback')
            with self.assertRaises(sqlite3.ProgrammingError):
                failed.execute('SELECT 1')
            with store.connect() as check:
                self.assertEqual(check.execute('SELECT body FROM config WHERE id=7').fetchone()[0], 'committed')
            (Path(tmp) / 'paperpilot.sqlite').unlink()
