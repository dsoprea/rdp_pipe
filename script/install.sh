#!/usr/bin/env bash
set -euo pipefail

usage_help() {
  echo "Usage: $(basename "$0") [-h]"
  echo "  Editable install of rdp_pipe (same as: pip install -e .)."
  echo "  Activate pyenv for .python-version before running (see README.md)."
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage_help
      exit 0
      ;;
    *)
      echo "error: unexpected argument: $1" >&2
      usage_help >&2
      exit 2
      ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "${ROOT}"

python -m pip install -e .

DESKTOP_INSTALL_SCRIPT="${ROOT}/script/support/install_rdp_pipe_desktop_entry.sh"
if [[ -x "${DESKTOP_INSTALL_SCRIPT}" ]]; then
  "${DESKTOP_INSTALL_SCRIPT}"
fi
