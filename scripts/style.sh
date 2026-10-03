#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REGION="${REGION:-china/guangxi}"
WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
YYYYMMDD="${YYYYMMDD:-$(date -u +%Y%m%d)}"
SESSION="${SESSION:-}"
STYLE_LOCALE="${STYLE_LOCALE:-}"
PMTILES_URL="${PMTILES_URL:-}"

for arg in "$@"; do
  case "${arg}" in
    --region=*) REGION="${arg#*=}" ;;
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}" ;;
    --session=*) SESSION="${arg#*=}" ;;
    --locale=*) STYLE_LOCALE="${arg#*=}" ;;
    --pmtiles-url=*) PMTILES_URL="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]\n' "$0"
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

args=(build style --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}")
[[ -n "${SESSION}" ]] && args+=(--session="${SESSION}")
[[ -n "${STYLE_LOCALE}" ]] && args+=(--locale="${STYLE_LOCALE}")
[[ -n "${PMTILES_URL}" ]] && args+=(--pmtiles-url="${PMTILES_URL}")

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build "${args[@]}"
