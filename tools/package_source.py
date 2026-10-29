"""Allowlisted source bundle; excludes runtime data and private research files."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent.parent
SINGLE = ['README.md', 'AGENTS.md', 'requirements.txt', 'run.sh', 'package.json', 'package-lock.json',
          '.gitignore', '.gitattributes', '启动 PaperPilot.command', '停止 PaperPilot.command',
          'tools/open-app.sh', 'tools/build_macos_app.py', 'tools/presentation-export.mjs',
          'PaperPilot.app/Contents/Info.plist', 'PaperPilot.app/Contents/MacOS/PaperPilot',
          'PaperPilot.app/Contents/Resources/PaperPilot.icns', 'paperpilot/conference_registry.json', 'tests/fixtures/conference-seed.json',
          'tools/export.mjs', 'tools/package_source.py', 'tools/build-graph.mjs',
          'tools/graph3d-entry.js', 'web/graph3d-licenses.txt']
TREES = {'paperpilot': {'.py', '.md'},
         'web': {'.html', '.css', '.js', '.mjs', '.svg', '.png', '.ico', '.icns', '.md'},
         'tests': {'.py', '.mjs', '.cjs'}, 'docs': {'.md'}}


def source_files():
    files = [ROOT/path for path in SINGLE]
    for directory, extensions in TREES.items():
        files.extend(path for path in (ROOT/directory).rglob('*')
                     if path.suffix in extensions and '__pycache__' not in path.parts)
    return sorted({path for path in files if path.is_file()
                   and not any(part.is_symlink() for part in [path, *path.parents])})


def build(destination=None):
    destination = Path(destination or ROOT/'output/PaperPilot-source.zip')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in source_files():
            archive.write(path, Path('PaperPilot')/path.relative_to(ROOT))
    return destination


if __name__ == '__main__':
    print(build())
