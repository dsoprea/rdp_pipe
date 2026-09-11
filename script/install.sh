#!/usr/bin/env bash
set -euo pipefail

install_root_directory="$(cd "$(dirname "$0")/.." && pwd)"
cd "${install_root_directory}"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/pip install -e ".[dev]"
