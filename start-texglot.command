#!/bin/bash
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/TeX/texbin:$PATH"
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  ./scripts/setup.sh
fi
exec .venv/bin/python scripts/start.py "$@"
