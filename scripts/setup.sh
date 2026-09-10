#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v uv >/dev/null; then
  echo "请先安装 uv：https://docs.astral.sh/uv/getting-started/installation/"
  exit 1
fi
export PYTHONUTF8=1
exec uv run --no-project --python 3.13 python scripts/setup.py "$@"
