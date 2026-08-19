#!/usr/bin/env bash
set -euo pipefail

BUILD_HOME="${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}"
SESSION="${HUAVD_MAP_BUILD_SESSION:-china-guangxi-20260818}"
DIR_MODE="${HUAVD_MAP_BUILD_DIR_MODE:-0750}"
CONFIG_DIR_MODE="${HUAVD_MAP_BUILD_CONFIG_DIR_MODE:-0755}"
FILE_MODE="${HUAVD_MAP_BUILD_FILE_MODE:-0644}"
COPY_CONFIG="${HUAVD_MAP_BUILD_COPY_CONFIG:-0}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

if [[ ! "${SESSION}" =~ ^[a-z0-9]+(-[a-z0-9]+)*-[0-9]{8}$ ]]; then
  printf 'invalid HUAVD_MAP_BUILD_SESSION: %s\n' "${SESSION}" >&2
  printf 'expected {region-slug}-{yyyymmdd}, e.g. china-guangxi-20260818\n' >&2
  exit 64
fi

mkdir -p \
  "${BUILD_HOME}/bin" \
  "${BUILD_HOME}/mirror" \
  "${BUILD_HOME}/cache/tags-filter" \
  "${BUILD_HOME}/staging/${SESSION}/layers" \
  "${BUILD_HOME}/outputs" \
  "${BUILD_HOME}/config/regions" \
  "${BUILD_HOME}/config/export-config"

chmod 0755 "${BUILD_HOME}" "${BUILD_HOME}/bin" "${BUILD_HOME}/config" "${BUILD_HOME}/config/regions" "${BUILD_HOME}/config/export-config"
chmod "${DIR_MODE}" \
  "${BUILD_HOME}/mirror" \
  "${BUILD_HOME}/cache" \
  "${BUILD_HOME}/cache/tags-filter" \
  "${BUILD_HOME}/staging" \
  "${BUILD_HOME}/staging/${SESSION}" \
  "${BUILD_HOME}/staging/${SESSION}/layers" \
  "${BUILD_HOME}/outputs"

if [[ "${COPY_CONFIG}" == "1" ]]; then
  cp -R "${REPO_ROOT}/config/." "${BUILD_HOME}/config/"
  find "${BUILD_HOME}/config" -type d -exec chmod "${CONFIG_DIR_MODE}" {} +
  find "${BUILD_HOME}/config" -type f -exec chmod "${FILE_MODE}" {} +
fi

printf 'huavd-map-build workdir initialized: %s\n' "${BUILD_HOME}"
printf 'session: %s\n' "${SESSION}"
