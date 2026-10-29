"""Build a relocatable macOS double-click launcher; no user paths or data embedded."""
from pathlib import Path
import plistlib
import shutil

ROOT = Path(__file__).resolve().parent.parent


def build():
    contents = ROOT / 'PaperPilot.app/Contents'
    (contents / 'MacOS').mkdir(parents=True, exist_ok=True)
    (contents / 'Resources').mkdir(exist_ok=True)
    executable = contents / 'MacOS/PaperPilot'
    executable.write_text('#!/bin/sh\nset -eu\ncd "$(dirname "$0")/../../.."\nexec ./tools/open-app.sh\n')
    executable.chmod(0o755)
    info = {'CFBundleName':'PaperPilot', 'CFBundleDisplayName':'PaperPilot',
            'CFBundleIdentifier':'local.paperpilot.desktop', 'CFBundleVersion':'1',
            'CFBundleShortVersionString':'1.0', 'CFBundleExecutable':'PaperPilot',
            'CFBundlePackageType':'APPL', 'CFBundleIconFile':'PaperPilot.icns', 'LSUIElement':True,
            'NSHighResolutionCapable':True}
    (contents / 'Info.plist').write_bytes(plistlib.dumps(info))
    shutil.copyfile(ROOT / 'web/icons/paperpilot.icns', contents / 'Resources/PaperPilot.icns')
    return contents.parent


if __name__ == '__main__':
    print(build())
