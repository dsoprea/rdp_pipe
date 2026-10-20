#!/usr/bin/env bash
set -euo pipefail

usage_help() {
  echo "Usage: $(basename "$0") [-h]"
  echo "  Install asset/rdp_pipe.desktop into ~/.local/share/applications/"
  echo "  for xdg-desktop-portal, the app menu, and KDE task switcher Name= mapping."
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

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SCRIPT_DIRECTORY}/../.." && pwd)"
SOURCE_DESKTOP_FILEPATH="${ROOT}/asset/rdp_pipe.desktop"
TARGET_APPLICATIONS_DIRECTORY="${HOME}/.local/share/applications"
TARGET_DESKTOP_FILEPATH="${TARGET_APPLICATIONS_DIRECTORY}/rdp_pipe.desktop"

if [[ ! -f "${SOURCE_DESKTOP_FILEPATH}" ]]; then
  echo "error: missing desktop entry source ${SOURCE_DESKTOP_FILEPATH}" >&2
  exit 1
fi

mkdir -p "${TARGET_APPLICATIONS_DIRECTORY}"
cp "${SOURCE_DESKTOP_FILEPATH}" "${TARGET_DESKTOP_FILEPATH}"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${TARGET_APPLICATIONS_DIRECTORY}" >/dev/null 2>&1 || true
fi

echo "installed ${TARGET_DESKTOP_FILEPATH}" >&2
echo "restart rdp sessions so portal registration and task switcher pick up the entry" >&2
