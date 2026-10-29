#!/bin/sh
# Finder supplies a minimal PATH. Discover installed tools without private paths.
set -eu
cd "$(dirname "$0")/.."
PATH="$HOME/.local/bin:$HOME/.npm-global/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v node >/dev/null 2>&1; then
  for bin in "$HOME"/.nvm/versions/node/*/bin; do
    [ ! -x "$bin/node" ] || PATH="$bin:$PATH"
  done
fi
if ! command -v codex >/dev/null 2>&1; then
  for bin in /Applications/Codex.app/Contents/Resources /Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS; do
    [ ! -x "$bin/codex" ] || PATH="$bin:$PATH"
  done
fi
export PATH
if [ "${1:-}" = '--stop' ]; then
  flag=--desktop-stop
else
  flag=--desktop
fi
# Errors are shown in a native dialog instead of disappearing with a background shell.
if message=$(./run.sh "$flag" 2>&1); then
  exit 0
fi
if [ "$(uname -s)" = Darwin ]; then
  /usr/bin/osascript - "$message" <<'APPLESCRIPT'
on run argv
  display alert "PaperPilot 未能完成操作" message (item 1 of argv) as warning
end run
APPLESCRIPT
else
  printf '%s\n' "$message" >&2
fi
exit 1
