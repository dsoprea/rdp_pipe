#!/usr/bin/env bash

# Semver and release git tags for rdp_pipe (pyproject.toml, vX.Y.Z).
# Source after set -euo pipefail.

RDP_PIPE_RELEASE_SUPPORT_SCRIPT_DIRECTORY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RDP_PIPE_REPOSITORY_ROOT="$(cd "${RDP_PIPE_RELEASE_SUPPORT_SCRIPT_DIRECTORY}/../.." && pwd)"
RDP_PIPE_PACKAGE_ARCHIVE_SLUG="rdp_pipe"

rdp_pipe_pyproject_toml_filepath() {
  printf '%s/pyproject.toml' "${RDP_PIPE_REPOSITORY_ROOT}"
}

rdp_pipe_read_semver_from_pyproject_toml() {
  local PYPROJECT_TOML_FILEPATH
  local VERSION_LINE

  PYPROJECT_TOML_FILEPATH="$(rdp_pipe_pyproject_toml_filepath)"

  if [[ ! -f "${PYPROJECT_TOML_FILEPATH}" ]]; then
    echo "error: missing ${PYPROJECT_TOML_FILEPATH}" >&2

    return 1
  fi

  VERSION_LINE="$(
    grep -E '^version[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"' "${PYPROJECT_TOML_FILEPATH}" | head -n 1 \
      | sed -E 's/^version[[:space:]]*=[[:space:]]*"([^"]+)".*/\1/'
  )"

  if [[ -z "${VERSION_LINE}" ]]; then
    echo "error: could not read version from ${PYPROJECT_TOML_FILEPATH}" >&2

    return 1
  fi

  printf '%s\n' "${VERSION_LINE}"
}

rdp_pipe_write_semver_to_pyproject_toml() {
  local NEW_VERSION="$1"
  local PYPROJECT_TOML_FILEPATH

  PYPROJECT_TOML_FILEPATH="$(rdp_pipe_pyproject_toml_filepath)"

  sed -i -E 's/^version[[:space:]]*=[[:space:]]*"[0-9]+\.[0-9]+\.[0-9]+"/version = "'"${NEW_VERSION}"'"/' \
    "${PYPROJECT_TOML_FILEPATH}"
}

rdp_pipe_semver_release_git_tag() {
  local SEMVER_VERSION="$1"

  printf 'v%s' "${SEMVER_VERSION}"
}

rdp_pipe_normalize_release_tag() {
  local RELEASE_TAG="$1"

  if [[ "${RELEASE_TAG}" == v* ]]; then
    printf '%s\n' "${RELEASE_TAG}"

    return 0
  fi

  if [[ "${RELEASE_TAG}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    printf 'v%s\n' "${RELEASE_TAG}"

    return 0
  fi

  printf '%s\n' "${RELEASE_TAG}"
}

rdp_pipe_bump_semver_version() {
  local BUMP_KIND="$1"
  local CURRENT_VERSION="$2"
  local MAJOR
  local MINOR
  local PATCH

  if [[ ! "${CURRENT_VERSION}" =~ ^([0-9]+)\.([0-9]+)\.([0-9]+)$ ]]; then
    echo "error: unsupported version format: ${CURRENT_VERSION}" >&2

    return 1
  fi

  MAJOR="${BASH_REMATCH[1]}"
  MINOR="${BASH_REMATCH[2]}"
  PATCH="${BASH_REMATCH[3]}"

  case "${BUMP_KIND}" in
    patch)
      PATCH="$((PATCH + 1))"
      ;;
    minor)
      MINOR="$((MINOR + 1))"
      PATCH=0
      ;;
    major)
      MAJOR="$((MAJOR + 1))"
      MINOR=0
      PATCH=0
      ;;
    *)
      echo "error: bump kind must be patch, minor, or major (got: ${BUMP_KIND})" >&2

      return 1
      ;;
  esac

  printf '%s.%s.%s\n' "${MAJOR}" "${MINOR}" "${PATCH}"
}

rdp_pipe_assert_repository_clean_for_bump() {
  if ! git -C "${RDP_PIPE_REPOSITORY_ROOT}" diff --quiet; then
    echo "error: repository working tree is not clean; commit or stash before bumping." >&2

    return 1
  fi

  if ! git -C "${RDP_PIPE_REPOSITORY_ROOT}" diff --cached --quiet; then
    echo "error: repository index is not clean; commit or stash before bumping." >&2

    return 1
  fi
}

rdp_pipe_resolve_previous_version_release_git_tag() {
  local AT_COMMIT="${1:-HEAD}"

  if ! git -C "${RDP_PIPE_REPOSITORY_ROOT}" describe --tags --abbrev=0 --match 'v*' "${AT_COMMIT}" >/dev/null 2>&1; then
    printf '%s' ""

    return 0
  fi

  git -C "${RDP_PIPE_REPOSITORY_ROOT}" describe --tags --abbrev=0 --match 'v*' "${AT_COMMIT}"
}

rdp_pipe_resolve_prior_release_git_tag() {
  local CURRENT_RELEASE_TAG="$1"
  local NORMALIZED_CURRENT_TAG
  local TAG_LINE
  local FOUND_CURRENT=0

  NORMALIZED_CURRENT_TAG="$(rdp_pipe_normalize_release_tag "${CURRENT_RELEASE_TAG}")"

  while IFS= read -r TAG_LINE; do
    if [[ "${FOUND_CURRENT}" -eq 1 ]]; then
      printf '%s' "${TAG_LINE}"

      return 0
    fi

    if [[ "${TAG_LINE}" == "${NORMALIZED_CURRENT_TAG}" ]]; then
      FOUND_CURRENT=1
    fi
  done < <(git -C "${RDP_PIPE_REPOSITORY_ROOT}" tag -l 'v*' --sort=-version:refname)

  printf '%s' ""
}

rdp_pipe_collect_version_release_changelog_bullet_lines() {
  local PREVIOUS_RELEASE_TAG="$1"
  local UNTIL_COMMIT="$2"
  local COMMIT_COUNT

  if [[ -z "${PREVIOUS_RELEASE_TAG}" ]]; then
    COMMIT_COUNT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" rev-list --count "${UNTIL_COMMIT}")"

    if [[ "${COMMIT_COUNT}" -eq 0 ]]; then
      printf '%s\n' "- (no commits in this release)"

      return 0
    fi

    git -C "${RDP_PIPE_REPOSITORY_ROOT}" log --format='- %s' "${UNTIL_COMMIT}"

    return 0
  fi

  COMMIT_COUNT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" rev-list --count \
    "${PREVIOUS_RELEASE_TAG}..${UNTIL_COMMIT}")"

  if [[ "${COMMIT_COUNT}" -eq 0 ]]; then
    printf '%s\n' "- (no commits in this release)"

    return 0
  fi

  git -C "${RDP_PIPE_REPOSITORY_ROOT}" log --format='- %s' "${PREVIOUS_RELEASE_TAG}..${UNTIL_COMMIT}"
}

rdp_pipe_build_version_release_tag_brief_summary() {
  local PREVIOUS_RELEASE_TAG="$1"
  local UNTIL_COMMIT="$2"
  local COMMIT_COUNT
  local FIRST_SUBJECT
  local BRIEF_SUMMARY
  local MAX_BRIEF_LENGTH=64

  if [[ -z "${PREVIOUS_RELEASE_TAG}" ]]; then
    COMMIT_COUNT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" rev-list --count "${UNTIL_COMMIT}")"
  else
    COMMIT_COUNT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" rev-list --count \
      "${PREVIOUS_RELEASE_TAG}..${UNTIL_COMMIT}")"
  fi

  if [[ "${COMMIT_COUNT}" -eq 0 ]]; then
    printf '%s' "version bump only"

    return 0
  fi

  if [[ -z "${PREVIOUS_RELEASE_TAG}" ]]; then
    FIRST_SUBJECT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" log -1 --format='%s' "${UNTIL_COMMIT}")"
  else
    FIRST_SUBJECT="$(git -C "${RDP_PIPE_REPOSITORY_ROOT}" log -1 --format='%s' "${PREVIOUS_RELEASE_TAG}..${UNTIL_COMMIT}")"
  fi

  BRIEF_SUMMARY="${FIRST_SUBJECT}"

  if [[ "${#BRIEF_SUMMARY}" -gt "${MAX_BRIEF_LENGTH}" ]]; then
    BRIEF_SUMMARY="${BRIEF_SUMMARY:0:MAX_BRIEF_LENGTH}…"
  fi

  printf '%s' "${BRIEF_SUMMARY}"
}

rdp_pipe_create_version_release_annotated_git_tag() {
  local RELEASE_TAG="$1"
  local PREVIOUS_RELEASE_TAG="$2"
  local UNTIL_COMMIT="$3"
  local NORMALIZED_RELEASE_TAG
  local BRIEF_SUMMARY
  local TAG_MESSAGE_FILEPATH

  NORMALIZED_RELEASE_TAG="$(rdp_pipe_normalize_release_tag "${RELEASE_TAG}")"

  if git -C "${RDP_PIPE_REPOSITORY_ROOT}" rev-parse --verify --quiet "refs/tags/${NORMALIZED_RELEASE_TAG}" >/dev/null; then
    echo "error: release tag already exists: ${NORMALIZED_RELEASE_TAG}" >&2

    return 1
  fi

  BRIEF_SUMMARY="$(rdp_pipe_build_version_release_tag_brief_summary \
    "${PREVIOUS_RELEASE_TAG}" \
    "${UNTIL_COMMIT}")"
  TAG_MESSAGE_FILEPATH="$(mktemp)"

  {
    printf '%s: %s\n\n' "${NORMALIZED_RELEASE_TAG}" "${BRIEF_SUMMARY}"
    rdp_pipe_collect_version_release_changelog_bullet_lines \
      "${PREVIOUS_RELEASE_TAG}" \
      "${UNTIL_COMMIT}"
    printf '\n'
  } >"${TAG_MESSAGE_FILEPATH}"

  echo "==> git tag -a ${NORMALIZED_RELEASE_TAG} (annotated release)" >&2
  git -C "${RDP_PIPE_REPOSITORY_ROOT}" tag \
    -a "${NORMALIZED_RELEASE_TAG}" \
    -F "${TAG_MESSAGE_FILEPATH}"

  rm -f "${TAG_MESSAGE_FILEPATH}"
}

rdp_pipe_write_version_json() {
  local VERSION_JSON_FILEPATH="$1"
  local GIT_REVISION="$2"
  local BUILT_AT="$3"
  local RELEASE_TAG="$4"
  local VERSION_JSON_DIRECTORY

  VERSION_JSON_DIRECTORY="$(dirname "${VERSION_JSON_FILEPATH}")"
  mkdir -p "${VERSION_JSON_DIRECTORY}"

  export GIT_REVISION BUILT_AT RELEASE_TAG VERSION_JSON_FILEPATH

  python -c "
import json
import os

version_record = {
    'revision': os.environ['GIT_REVISION'],
    'timestamp': os.environ['BUILT_AT'],
    'tag': os.environ['RELEASE_TAG'],
}
with open(os.environ['VERSION_JSON_FILEPATH'], 'w', encoding='utf-8') as handle:
    json.dump(version_record, handle, indent=2)
    handle.write('\n')
"
}

rdp_pipe_read_version_json_field() {
  local VERSION_JSON_FILEPATH="$1"
  local FIELD_NAME="$2"

  python -c "
import json
import sys

with open(sys.argv[1], encoding='utf-8') as handle:
    version_record = json.load(handle)
field_name = sys.argv[2]
value = version_record.get(field_name)
if not isinstance(value, str) or len(value) == 0:
    sys.stderr.write(f'error: {sys.argv[1]} missing {field_name} string\\n')
    sys.exit(1)
print(value, end='')
" "${VERSION_JSON_FILEPATH}" "${FIELD_NAME}"
}
