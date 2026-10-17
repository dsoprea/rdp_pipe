#!/usr/bin/env bash

# Production wheel and sdist build (python -m build). No semver bump or packaging.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage_help() {
  echo "Usage: $(basename "$0") [-h]"
  echo "  -h, --help  Show this help"
  echo ""
  echo "Install the build frontend and run python -m build in the rdp_pipe package."
  echo "For version bump, git tag, and deploy archive, use script/package.sh."
  echo "Activate pyenv for .python-version before running (see README.md)."
}

die() {
  echo "error: $*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage_help
      exit 0
      ;;
    *)
      die "unknown argument: $1 (see -h)"
      ;;
  esac
done

cd "${ROOT}"

echo "==> python -m pip install -q build (${ROOT})" >&2
python -m pip install -q build

echo "==> rm -rf dist (${ROOT})" >&2
rm -rf dist

echo "==> python -m build (${ROOT})" >&2
python -m build

WHEEL_COUNT="$(find dist -maxdepth 1 -type f -name '*.whl' 2>/dev/null | wc -l)"
SDIST_COUNT="$(find dist -maxdepth 1 -type f -name '*.tar.gz' 2>/dev/null | wc -l)"

if [[ "${WHEEL_COUNT}" -lt 1 ]]; then
  die "expected at least one wheel in ${ROOT}/dist after build."
fi

if [[ "${SDIST_COUNT}" -lt 1 ]]; then
  die "expected at least one sdist in ${ROOT}/dist after build."
fi

echo "==> rdp_pipe build output: ${ROOT}/dist" >&2
