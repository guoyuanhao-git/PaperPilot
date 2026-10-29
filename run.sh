#!/bin/sh
set -eu
cd "$(dirname "$0")"
PAPERPILOT_PYTHON="${PAPERPILOT_PYTHON:-}"
if [ -z "$PAPERPILOT_PYTHON" ]; then
  if [ -x .venv/bin/python ]; then
    PAPERPILOT_PYTHON="$PWD/.venv/bin/python"
  elif [ -x "$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3" ]; then
    PAPERPILOT_PYTHON="$HOME/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
  else
    PAPERPILOT_PYTHON=python3
  fi
fi
export PAPERPILOT_PYTHON
if [ "${1:-}" = "--connect-model" ]; then
  shift
  exec "$PAPERPILOT_PYTHON" -m paperpilot.model_setup "$@"
fi
if ! "$PAPERPILOT_PYTHON" -c 'import pdfplumber,pypdfium2,pypdf' >/dev/null 2>&1; then
  echo '请先创建虚拟环境并安装依赖：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt'
  exit 1
fi
if [ ! -f node_modules/katex/dist/katex.min.js ]; then
  echo '请先执行 npm install 安装公式排版依赖。'
  exit 1
fi
case "${1:-}" in
  --desktop) shift; exec "$PAPERPILOT_PYTHON" -m paperpilot.launcher "$@" ;;
  --desktop-stop) shift; exec "$PAPERPILOT_PYTHON" -m paperpilot.launcher --stop "$@" ;;
  *) exec "$PAPERPILOT_PYTHON" -m paperpilot.server "$@" ;;
esac
