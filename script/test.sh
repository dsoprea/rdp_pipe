#!/usr/bin/env bash
set -euo pipefail

test_root_directory="$(cd "$(dirname "$0")/.." && pwd)"
cd "${test_root_directory}"

if [[ ! -x .venv/bin/python ]]; then
  echo "error: run script/install.sh first" >&2
  exit 1
fi

.venv/bin/python -m pytest -q
