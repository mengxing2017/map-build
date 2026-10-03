#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "${PYTHON}" ]] || { printf 'Python 3 is required; run make setup\n' >&2; exit 5; }

args=(
  workspace init
  "--workdir=${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}"
  "--session=${HUAVD_MAP_BUILD_SESSION:-china-guangxi-20260818}"
  "--directory-mode=${HUAVD_MAP_BUILD_DIR_MODE:-0750}"
  "--config-directory-mode=${HUAVD_MAP_BUILD_CONFIG_DIR_MODE:-0755}"
  "--file-mode=${HUAVD_MAP_BUILD_FILE_MODE:-0644}"
)
[[ "${HUAVD_MAP_BUILD_COPY_CONFIG:-0}" == "1" ]] && args+=(--copy-config)

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build "${args[@]}"
