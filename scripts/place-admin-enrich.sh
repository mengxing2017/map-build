#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
REGION="${REGION:-china/guangxi}"
WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
YYYYMMDD="${YYYYMMDD:-$(date -u +%Y%m%d)}"
SESSION="${SESSION:-}"
INPUT=""

for arg in "$@"; do
  case "${arg}" in
    --input=*) INPUT="${arg#*=}" ;;
    --region=*) REGION="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}" ;;
    --session=*) SESSION="${arg#*=}" ;;
    --workdir=*) WORKDIR="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --input=<source.osm.pbf> --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) printf 'ERROR: unknown argument: %s\n' "${arg}" >&2; exit 2 ;;
  esac
done

[[ -n "${INPUT}" ]] || { printf 'ERROR: --input is required\n' >&2; exit 2; }
PYTHON="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "${PYTHON}" ]] || { printf 'Python 3 is required; run make setup\n' >&2; exit 5; }

args=(build place-admin-enrich --input="${INPUT}" --region="${REGION}" \
  --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}")
[[ -n "${SESSION}" ]] && args+=(--session="${SESSION}")

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build "${args[@]}"
