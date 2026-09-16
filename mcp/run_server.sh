#!/usr/bin/env bash
set -euo pipefail

usage_help() {
  echo "Usage: $(basename "$0") [-h]"
  echo "  Launch the rdp_pipe MCP stdio server with the repo pyenv interpreter."
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

mcp_directory_path="$(cd "$(dirname "$0")" && pwd)"
repository_root="$(cd "${mcp_directory_path}/.." && pwd)"
python_version_filepath="${repository_root}/.python-version"

if [[ ! -f "${python_version_filepath}" ]]; then
  echo "error: missing ${python_version_filepath}" >&2
  exit 1
fi

export PYENV_VERSION="$(tr -d '[:space:]' < "${python_version_filepath}")"

if ! command -v pyenv >/dev/null 2>&1; then
  echo "error: pyenv not found on PATH; install pyenv or adjust MCP command" >&2
  exit 1
fi

cd "${repository_root}"

rdpr_command="$(pyenv which rdpr)"
export RDPR_COMMAND="${rdpr_command}"

exec pyenv exec python "${mcp_directory_path}/server.py"
