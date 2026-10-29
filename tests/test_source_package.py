import tempfile
import unittest
import zipfile
from pathlib import Path
from tools import package_source


class SourcePackage(unittest.TestCase):
    def test_complete_source_without_user_state(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = package_source.build(Path(temp) / 'source.zip')
            with zipfile.ZipFile(bundle) as archive:
                names = {name.removeprefix('PaperPilot/') for name in archive.namelist()}
                for required in ('AGENTS.md', 'docs/WINDOWS_HANDOFF.md',
                                 'paperpilot/conference_registry.json', 'web/conferences/logic.mjs',
                                 'tests/fixtures/conference-seed.json', 'tests/conference-rules.test.mjs', 'tests/reader-split.test.cjs',
                                 'web/icons/papers-cool.ico', 'paperpilot/prompts/reading.md'):
                    self.assertIn(required, names)
                for name in names:
                    self.assertNotIn(Path(name).parts[0],
                                     {'data', 'memory', 'output', 'tmp', 'node_modules', 'skills', '论文重写参考'})
                    self.assertNotIn('__pycache__', Path(name).parts)
                    self.assertFalse(name.startswith('.env'))
                self.assertNotIn('/Users/', archive.read('PaperPilot/AGENTS.md').decode())
