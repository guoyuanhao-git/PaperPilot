import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from tools import package_source


class SourcePackage(unittest.TestCase):
    def test_windows_entrypoints_are_included_when_present(self):
        # The Windows branch owns these files; verify packaging without requiring
        # a partial merge of its launcher into the macOS working tree.
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve() / 'source'
            root.mkdir()
            entrypoints = ('run.cmd', '启动 PaperPilot.cmd', '停止 PaperPilot.cmd')
            for name in entrypoints:
                (root / name).write_bytes(b'@echo off\r\nexit /b 0\r\n')
            with patch.object(package_source, 'ROOT', root):
                bundle = package_source.build(Path(temp) / 'source.zip')
            with zipfile.ZipFile(bundle) as archive:
                for name in entrypoints:
                    self.assertEqual(archive.read('PaperPilot/' + name), (root / name).read_bytes())

    def test_complete_source_without_user_state(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = package_source.build(Path(temp) / 'source.zip')
            with zipfile.ZipFile(bundle) as archive:
                names = {name.removeprefix('PaperPilot/') for name in archive.namelist()}
                for required in ('AGENTS.md', 'docs/WINDOWS_HANDOFF.md', 'docs/GETTING_STARTED.md',
                                 'docs/assets/readme/banner.svg', 'docs/assets/readme/discovery.png',
                                 'docs/assets/readme/reading.png', 'docs/assets/readme/knowledge.png',
                                 'paperpilot/conference_registry.json', 'web/conferences/logic.mjs',
                                 'tests/fixtures/conference-seed.json', 'tests/conference-rules.test.mjs', 'tests/reader-split.test.cjs',
                                 'web/icons/papers-cool.ico', 'paperpilot/prompts/reading.md'):
                    self.assertIn(required, names)
                for entrypoint in ('run.cmd', '启动 PaperPilot.cmd', '停止 PaperPilot.cmd'):
                    if (package_source.ROOT / entrypoint).exists():
                        self.assertIn(entrypoint, names)
                for name in names:
                    self.assertNotIn(Path(name).parts[0],
                                     {'data', 'memory', 'output', 'tmp', 'node_modules', 'skills', '论文重写参考'})
                    self.assertNotIn('__pycache__', Path(name).parts)
                    self.assertFalse(name.startswith('.env'))
                self.assertNotIn('/Users/', archive.read('PaperPilot/AGENTS.md').decode())
