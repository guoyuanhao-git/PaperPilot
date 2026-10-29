import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from paperpilot.file_lock import file_lock


class FileLockTests(unittest.TestCase):
    def test_cross_process_contention_and_exception_release(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lock'
            code = "from paperpilot.file_lock import file_lock; import sys; " \
                   "ctx=file_lock(sys.argv[1], blocking=False); ctx.__enter__(); ctx.__exit__(None,None,None)"
            with self.assertRaisesRegex(ValueError, 'test'):
                with file_lock(path):
                    result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    raise ValueError('test')
            result = subprocess.run([sys.executable, '-c', code, str(path)], capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
