#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REGION="${REGION:-china/guangxi}"
WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
YYYYMMDD="${YYYYMMDD:-$(date -u +%Y%m%d)}"
SESSION="${SESSION:-}"
LAYERS=""

for arg in "$@"; do
  case "${arg}" in
    --region=*) REGION="${arg#*=}" ;;
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}" ;;
    --session=*) SESSION="${arg#*=}" ;;
    --layers=*) LAYERS="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --layers=<layer[,layer...]> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) printf 'ERROR: unknown argument: %s\n' "${arg}" >&2; exit 2 ;;
  esac
done

[[ -n "${LAYERS}" && "${LAYERS}" != "all" ]] \
  || { printf 'ERROR: --layers must name the effective base layers\n' >&2; exit 2; }
PYTHON="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "${PYTHON}" ]] || { printf 'Python 3 is required; run make setup\n' >&2; exit 5; }

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build build profile-transform \
    --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" \
    --layers="${LAYERS}" ${SESSION:+--session="${SESSION}"}
