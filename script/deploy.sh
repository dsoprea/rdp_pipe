#!/usr/bin/env bash

# Upload a package.sh archive to PyPI with twine.

set -euo pipefail

SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIRECTORY}/.." && pwd)"
RELEASES_DIRECTORY_PATH="${REPOSITORY_ROOT}/releases/pypi"

# shellcheck source=support/rdp_pipe_release.sh
source "${SCRIPT_DIRECTORY}/support/rdp_pipe_release.sh"

usage_help() {
  echo "Usage: $(basename "$0") [-h] <archive_filepath>"
  echo "  -h, --help  Show this help"
  echo ""
  echo "Extract a deploy archive from script/package.sh, run twine check, and"
  echo "upload dist/* to PyPI. Configure credentials via ~/.pypirc or"
  echo "TWINE_USERNAME and TWINE_PASSWORD. Optional TWINE_REPOSITORY_URL for"
  echo "TestPyPI (for example https://test.pypi.org/legacy/)."
  echo "Writes releases/pypi/X.Y.Z.md and commits it when the tree is clean."
}

die() {
  echo "error: $*" >&2
  exit 1
}

ARCHIVE_FILEPATH=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage_help
      exit 0
      ;;
    *)
      if [[ -n "${ARCHIVE_FILEPATH}" ]]; then
        die "unexpected extra argument: $1 (see -h)"
      fi
      ARCHIVE_FILEPATH="$1"
      shift
      ;;
  esac
done

if [[ -z "${ARCHIVE_FILEPATH}" ]]; then
  die "missing required parameter: package_filepath"
fi

if [[ ! -f "${ARCHIVE_FILEPATH}" ]]; then
  die "archive not found: ${ARCHIVE_FILEPATH}"
fi

cd "${REPOSITORY_ROOT}"

echo "==> python -m pip install -q twine build" >&2
python -m pip install -q twine build

EXTRACT_DIRECTORY="$(mktemp -d)"
trap 'rm -rf "${EXTRACT_DIRECTORY}"' EXIT

echo "==> extracting archive ${ARCHIVE_FILEPATH} to ${EXTRACT_DIRECTORY}" >&2
tar -xzf "${ARCHIVE_FILEPATH}" -C "${EXTRACT_DIRECTORY}"

VERSION_JSON_FILEPATH="${EXTRACT_DIRECTORY}/dist/internal/.version.json"

if [[ ! -f "${VERSION_JSON_FILEPATH}" ]]; then
  die "archive missing dist/internal/.version.json"
fi

DIST_DIRECTORY="${EXTRACT_DIRECTORY}/dist"

if [[ ! -d "${DIST_DIRECTORY}" ]]; then
  die "archive missing dist/"
fi

WHEEL_COUNT="$(find "${DIST_DIRECTORY}" -maxdepth 1 -type f -name '*.whl' | wc -l)"

if [[ "${WHEEL_COUNT}" -lt 1 ]]; then
  die "archive missing wheel in dist/"
fi

RELEASE_TAG="$(rdp_pipe_read_version_json_field "${VERSION_JSON_FILEPATH}" tag)"
DEPLOYED_COMMIT="$(rdp_pipe_read_version_json_field "${VERSION_JSON_FILEPATH}" revision)"
NORMALIZED_RELEASE_TAG="$(rdp_pipe_normalize_release_tag "${RELEASE_TAG}")"
VERSION_LABEL="${NORMALIZED_RELEASE_TAG#v}"

echo "==> twine check (${DIST_DIRECTORY})" >&2
twine check "${DIST_DIRECTORY}"/*.whl "${DIST_DIRECTORY}"/*.tar.gz

TWINE_UPLOAD_ARGUMENTS=(upload "${DIST_DIRECTORY}"/*.whl "${DIST_DIRECTORY}"/*.tar.gz)

if [[ -n "${TWINE_REPOSITORY_URL:-}" ]]; then
  TWINE_UPLOAD_ARGUMENTS+=(--repository-url "${TWINE_REPOSITORY_URL}")
fi

echo "==> twine upload (rdp_pipe ${NORMALIZED_RELEASE_TAG})" >&2
twine "${TWINE_UPLOAD_ARGUMENTS[@]}"

PREVIOUS_RELEASE_TAG="$(rdp_pipe_resolve_prior_release_git_tag "${NORMALIZED_RELEASE_TAG}")"
CHANGELOG_FILEPATH="${RELEASES_DIRECTORY_PATH}/${VERSION_LABEL}.md"

mkdir -p "${RELEASES_DIRECTORY_PATH}"

{
  printf '# PyPI release %s\n\n' "${NORMALIZED_RELEASE_TAG}"
  printf 'Revision: `%s`\n\n' "${DEPLOYED_COMMIT}"
  printf '## Changes\n\n'
  rdp_pipe_collect_version_release_changelog_bullet_lines \
    "${PREVIOUS_RELEASE_TAG}" \
    "${DEPLOYED_COMMIT}"
  printf '\n'
} >"${CHANGELOG_FILEPATH}"

echo "==> wrote ${CHANGELOG_FILEPATH}" >&2

if git -C "${REPOSITORY_ROOT}" diff --quiet && git -C "${REPOSITORY_ROOT}" diff --cached --quiet; then
  git -C "${REPOSITORY_ROOT}" add "${CHANGELOG_FILEPATH}"
  git -C "${REPOSITORY_ROOT}" commit -m "$(cat <<EOF
releases/pypi: record ${NORMALIZED_RELEASE_TAG} upload.
EOF
)"
else
  echo "warning: working tree not clean; skipped git commit for ${CHANGELOG_FILEPATH}" >&2
fi

echo "==> uploaded rdp_pipe ${NORMALIZED_RELEASE_TAG} to PyPI" >&2
