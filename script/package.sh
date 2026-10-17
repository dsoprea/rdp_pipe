#!/usr/bin/env bash

# Semver bump, release git tag, Python build, and deploy archive.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="${ROOT}"
BUILD_SCRIPT="${SCRIPT_DIRECTORY}/build.sh"

# shellcheck source=support/rdp_pipe_release.sh
source "${SCRIPT_DIRECTORY}/support/rdp_pipe_release.sh"

usage_help() {
  echo "Usage: $(basename "$0") [-h] patch|minor|major"
  echo "  -h, --help  Show this help"
  echo ""
  echo "Requires a clean git tree. Bumps version in pyproject.toml, commits,"
  echo "creates annotated vX.Y.Z from commit subjects since the previous v* tag,"
  echo "runs script/build.sh, and packs build/archives/vX.Y.Z_${RDP_PIPE_PACKAGE_ARCHIVE_SLUG}.tar.gz."
  echo "Stdout is the archive filepath relative to your cwd only (progress on stderr)."
  echo "Activate pyenv for .python-version before running (see README.md)."
}

die() {
  echo "error: $*" >&2
  exit 1
}

BUMP_KIND=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h | --help)
      usage_help
      exit 0
      ;;
    patch | minor | major)
      if [[ -n "${BUMP_KIND}" ]]; then
        die "bump kind specified more than once"
      fi
      BUMP_KIND="$1"
      shift
      ;;
    *)
      die "unknown argument: $1 (see -h)"
      ;;
  esac
done

if [[ -z "${BUMP_KIND}" ]]; then
  die "missing required parameter: bump (patch, minor, or major)"
fi

INVOCATION_DIRECTORY="$(pwd)"

cd "${ROOT}"

rdp_pipe_assert_repository_clean_for_bump

PREVIOUS_RELEASE_TAG="$(rdp_pipe_resolve_previous_version_release_git_tag HEAD)"
COMMIT_BEFORE_BUMP="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"

CURRENT_VERSION="$(rdp_pipe_read_semver_from_pyproject_toml)"
NEW_VERSION="$(rdp_pipe_bump_semver_version "${BUMP_KIND}" "${CURRENT_VERSION}")"
RELEASE_TAG="$(rdp_pipe_semver_release_git_tag "${NEW_VERSION}")"

if git -C "${REPOSITORY_ROOT}" rev-parse --verify --quiet "refs/tags/${RELEASE_TAG}" >/dev/null; then
  die "release tag already exists: ${RELEASE_TAG}"
fi

echo "==> bump ${CURRENT_VERSION} -> ${NEW_VERSION} (${BUMP_KIND})" >&2

rdp_pipe_write_semver_to_pyproject_toml "${NEW_VERSION}"

git -C "${REPOSITORY_ROOT}" add pyproject.toml
git -C "${REPOSITORY_ROOT}" commit -m "$(cat <<EOF
rdp_pipe: release ${RELEASE_TAG}.

Version bump (${BUMP_KIND}) ${CURRENT_VERSION} -> ${NEW_VERSION}.
EOF
)"

if [[ ! -x "${BUILD_SCRIPT}" ]]; then
  die "missing executable build script: ${BUILD_SCRIPT}"
fi

"${BUILD_SCRIPT}"

rdp_pipe_create_version_release_annotated_git_tag \
  "${RELEASE_TAG}" \
  "${PREVIOUS_RELEASE_TAG}" \
  "${COMMIT_BEFORE_BUMP}"

GIT_REVISION="$(git -C "${REPOSITORY_ROOT}" rev-parse HEAD)"
BUILT_AT="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

VERSION_JSON_DIRECTORY="${ROOT}/dist/internal"
VERSION_JSON_FILEPATH="${VERSION_JSON_DIRECTORY}/.version.json"
BUILD_DIRECTORY="${ROOT}/build"
ARCHIVES_DIRECTORY="${BUILD_DIRECTORY}/archives"
ARCHIVE_FILEPATH="${ARCHIVES_DIRECTORY}/${RELEASE_TAG}_${RDP_PIPE_PACKAGE_ARCHIVE_SLUG}.tar.gz"

mkdir -p "${ARCHIVES_DIRECTORY}"

rdp_pipe_write_version_json \
  "${VERSION_JSON_FILEPATH}" \
  "${GIT_REVISION}" \
  "${BUILT_AT}" \
  "${RELEASE_TAG}"

echo "==> wrote ${VERSION_JSON_FILEPATH}" >&2

echo "==> packing archive ${ARCHIVE_FILEPATH}" >&2
tar -czf "${ARCHIVE_FILEPATH}" -C "${ROOT}" dist

echo "==> rdp_pipe deploy archive: ${ARCHIVE_FILEPATH}" >&2

ARCHIVE_RELATIVE_FILEPATH="$(realpath --relative-to="${INVOCATION_DIRECTORY}" "${ARCHIVE_FILEPATH}")"

printf '%s\n' "${ARCHIVE_RELATIVE_FILEPATH}"
