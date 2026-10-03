#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REGION="${REGION:-china/guangxi}"
WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
LIMIT_RATE="${LIMIT_RATE:-10m}"

for arg in "$@"; do
  case "${arg}" in
    --region=*) REGION="${arg#*=}" ;;
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --limit-rate=*) LIMIT_RATE="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--workdir=<path>] [--limit-rate=10m]\n' "$0"
      exit 0
      ;;
    *) printf 'ERROR: unknown argument: %s\n' "${arg}" >&2; exit 2 ;;
  esac
done

PYTHON="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "${PYTHON}" ]] || { printf 'Python 3 is required; run make setup\n' >&2; exit 5; }

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build build fetch \
    --region="${REGION}" --workdir="${WORKDIR}" --limit-rate="${LIMIT_RATE}"
