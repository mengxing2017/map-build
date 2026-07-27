#!/usr/bin/env bash

set -euo pipefail

HUAVD_MAP_BUILD_COMMON_LOADED=1

HUAVD_EXIT_OK=0
HUAVD_EXIT_ERROR=1
HUAVD_EXIT_INPUT=2
HUAVD_EXIT_VERIFY=3
HUAVD_EXIT_DISK=4
HUAVD_EXIT_REMOTE_OR_TOOL=5

if [[ -z "${HUAVD_MAP_BUILD_LIB_DIR:-}" ]]; then
  HUAVD_MAP_BUILD_LIB_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
fi
REPO_ROOT="${REPO_ROOT:-$(cd -- "${HUAVD_MAP_BUILD_LIB_DIR}/../.." && pwd)}"
CONFIG_DIR="${CONFIG_DIR:-${REPO_ROOT}/config}"
WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
REGION="${REGION:-china/guangxi}"
YYYYMM="${YYYYMM:-$(date -u +%Y%m)}"
ROLE="${ROLE:-}"
SESSION="${SESSION:-}"

if [[ -z "${NO_COLOR:-}" && -t 2 ]]; then
  HUAVD_COLOR_INFO=$'\033[32m'
  HUAVD_COLOR_WARN=$'\033[33m'
  HUAVD_COLOR_ERROR=$'\033[31m'
  HUAVD_COLOR_RESET=$'\033[0m'
else
  HUAVD_COLOR_INFO=""
  HUAVD_COLOR_WARN=""
  HUAVD_COLOR_ERROR=""
  HUAVD_COLOR_RESET=""
fi

timestamp_utc() {
  date -u +%Y-%m-%dT%H:%M:%SZ
}

log_info() {
  printf '%sINFO%s [%s] %s\n' "${HUAVD_COLOR_INFO}" "${HUAVD_COLOR_RESET}" "$(timestamp_utc)" "$*" >&2
}

log_warn() {
  printf '%sWARN%s [%s] %s\n' "${HUAVD_COLOR_WARN}" "${HUAVD_COLOR_RESET}" "$(timestamp_utc)" "$*" >&2
}

log_error() {
  printf '%sERROR%s [%s] %s\n' "${HUAVD_COLOR_ERROR}" "${HUAVD_COLOR_RESET}" "$(timestamp_utc)" "$*" >&2
}

die() {
  local code="$1"
  shift
  log_error "$*"
  exit "${code}"
}

require_cmd() {
  local missing=()
  local cmd
  for cmd in "$@"; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${cmd}")
    fi
  done
  if ((${#missing[@]} > 0)); then
    die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "missing required command(s): ${missing[*]}"
  fi
}

require_file() {
  local path="$1"
  [[ -f "${path}" ]] || die "${HUAVD_EXIT_INPUT}" "required file does not exist: ${path}"
}

require_dir() {
  local path="$1"
  [[ -d "${path}" ]] || die "${HUAVD_EXIT_INPUT}" "required directory does not exist: ${path}"
}

ensure_dir() {
  local path="$1"
  if ! mkdir -p "${path}"; then
    die "${HUAVD_EXIT_DISK}" "failed to create directory: ${path}"
  fi
}

is_abs_path() {
  [[ "$1" == /* ]]
}

abs_path() {
  local path="$1"
  if is_abs_path "${path}"; then
    printf '%s\n' "${path}"
  else
    printf '%s/%s\n' "$(pwd)" "${path}"
  fi
}

slugify_region() {
  local region="$1"
  [[ "${region}" =~ ^[a-z0-9]+(/[a-z0-9-]+)*$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid region id: ${region}; expected lowercase like china/guangxi"
  printf '%s\n' "${region//\//-}"
}

validate_yyyymm() {
  local yyyymm="$1"
  [[ "${yyyymm}" =~ ^[0-9]{6}$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid YYYYMM: ${yyyymm}; expected 6 digits like 202607"
}

yyyymm_dash() {
  local yyyymm="$1"
  validate_yyyymm "${yyyymm}"
  printf '%s-%s\n' "${yyyymm:0:4}" "${yyyymm:4:2}"
}

session_from_region_yyyymm() {
  local region="$1"
  local yyyymm="$2"
  validate_yyyymm "${yyyymm}"
  printf '%s-%s\n' "$(slugify_region "${region}")" "${yyyymm}"
}

validate_session() {
  local session="$1"
  [[ "${session}" =~ ^[a-z0-9]+(-[a-z0-9]+)*-[0-9]{6}$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid SESSION: ${session}; expected {region-slug}-{yyyymm}, e.g. china-guangxi-202607"
}

session_yyyymm() {
  local session="$1"
  validate_session "${session}"
  printf '%s\n' "${session##*-}"
}

session_region_slug() {
  local session="$1"
  validate_session "${session}"
  printf '%s\n' "${session%-??????}"
}

normalize_session_vars() {
  validate_yyyymm "${YYYYMM}"
  if [[ -z "${SESSION}" ]]; then
    SESSION="$(session_from_region_yyyymm "${REGION}" "${YYYYMM}")"
  else
    validate_session "${SESSION}"
    YYYYMM="$(session_yyyymm "${SESSION}")"
  fi
}

outputs_dir() {
  printf '%s/outputs\n' "${WORKDIR}"
}

mirror_dir() {
  printf '%s/mirror\n' "${WORKDIR}"
}

tags_filter_cache_dir() {
  printf '%s/cache/tags-filter\n' "${WORKDIR}"
}

configs_cache_dir() {
  printf '%s/cache/configs\n' "${WORKDIR}"
}

pack_cache_dir() {
  printf '%s/cache/pack\n' "${WORKDIR}"
}

import_cache_dir() {
  printf '%s/cache/import\n' "${WORKDIR}"
}

staging_dir() {
  normalize_session_vars
  printf '%s/staging/%s\n' "${WORKDIR}" "${SESSION}"
}

layers_dir() {
  printf '%s/layers\n' "$(staging_dir)"
}

export_config_staging_dir() {
  printf '%s/export-config\n' "$(staging_dir)"
}

region_slug() {
  slugify_region "${REGION}"
}

artifact_stem() {
  local role="${1:-${ROLE}}"
  printf '%s-%s.%s\n' "$(region_slug)" "${YYYYMM}" "${role}"
}

build_pmtiles_path() {
  local role="${1:-${ROLE}}"
  printf '%s/%s.pmtiles\n' "$(outputs_dir)" "$(artifact_stem "${role}")"
}

build_manifest_path() {
  local role="${1:-${ROLE}}"
  printf '%s/%s.manifest.json\n' "$(outputs_dir)" "$(artifact_stem "${role}")"
}

build_attribution_path() {
  local role="${1:-${ROLE}}"
  printf '%s/%s.attribution.json\n' "$(outputs_dir)" "$(artifact_stem "${role}")"
}

build_sha512_path() {
  local role="${1:-${ROLE}}"
  printf '%s/%s.pmtiles.sha512\n' "$(outputs_dir)" "$(artifact_stem "${role}")"
}

relative_output_path() {
  local path="$1"
  printf 'outputs/%s\n' "$(basename -- "${path}")"
}

resolve_workspace_path() {
  local path="$1"
  if is_abs_path "${path}"; then
    printf '%s\n' "${path}"
    return
  fi
  case "${path}" in
    mirror/*|cache/*|staging/*|outputs/*)
      printf '%s/%s\n' "${WORKDIR}" "${path}"
      ;;
    *)
      if [[ -e "${path}" ]]; then
        abs_path "${path}"
      else
        printf '%s/%s\n' "${WORKDIR}" "${path}"
      fi
      ;;
  esac
}

role_list() {
  local role="${1:-${ROLE}}"
  case "${role}" in
    base) printf 'base\n' ;;
    building) printf 'building\n' ;;
    both) printf 'base\nbuilding\n' ;;
    *) die "${HUAVD_EXIT_INPUT}" "invalid role: ${role}; expected base, building, or both" ;;
  esac
}

write_sha512_file() {
  local file="$1"
  require_cmd sha512sum
  require_file "${file}"
  (cd -- "$(dirname -- "${file}")" && sha512sum "$(basename -- "${file}")" > "$(basename -- "${file}").sha512")
}

sha512_value() {
  local file="$1"
  require_cmd sha512sum
  require_file "${file}"
  sha512sum "${file}" | awk '{print $1}'
}

cmd_version() {
  local cmd="$1"
  local output
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    printf 'missing\n'
    return
  fi

  if output="$("${cmd}" --version 2>&1)" && [[ -n "${output}" ]]; then
    printf '%s\n' "${output}" | head -n 1 | sed 's/[[:space:]]*$//'
    return
  fi
  if output="$("${cmd}" version 2>&1)" && [[ -n "${output}" ]]; then
    printf '%s\n' "${output}" | head -n 1 | sed 's/[[:space:]]*$//'
    return
  fi
  if output="$("${cmd}" -version 2>&1)" && [[ -n "${output}" ]]; then
    printf '%s\n' "${output}" | head -n 1 | sed 's/[[:space:]]*$//'
  fi
}

parse_common_arg() {
  local arg="$1"
  case "${arg}" in
    --workdir=*) WORKDIR="${arg#*=}"; return 0 ;;
    --region=*) REGION="${arg#*=}"; return 0 ;;
    --yyyymm=*) YYYYMM="${arg#*=}"; SESSION=""; return 0 ;;
    --session=*) SESSION="${arg#*=}"; return 0 ;;
    --role=*) ROLE="${arg#*=}"; return 0 ;;
    *) return 1 ;;
  esac
}
