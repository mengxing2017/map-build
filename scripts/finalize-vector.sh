#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
REGION="${REGION:-china/guangxi}"
YYYYMMDD="${YYYYMMDD:-$(date -u +%Y%m%d)}"
SESSION="${SESSION:-}"
ROLE="${ROLE:-}"
BUNDLE_ID="${HUAVD_MAP_BUNDLE_ID:-}"
ACTIVATION="${HUAVD_MAP_ACTIVATION:-manual}"

for arg in "$@"; do
  case "${arg}" in
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --region=*) REGION="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}" ;;
    --session=*) SESSION="${arg#*=}" ;;
    --role=*) ROLE="${arg#*=}" ;;
    --bundle-id=*) BUNDLE_ID="${arg#*=}" ;;
    --activation=*) ACTIVATION="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD] [--session=<session>] [--bundle-id=<id>] [--activation=<mode>]\n' "$0"
      exit 0
      ;;
    *) printf 'ERROR: unknown argument: %s\n' "${arg}" >&2; exit 2 ;;
  esac
done

case "${ROLE}" in
  base|building) ;;
  *) printf 'ERROR: vector finalization role must be base or building\n' >&2; exit 2 ;;
esac

PYTHON="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
[[ -n "${PYTHON}" ]] || { printf 'ERROR: Python 3 is required; run make setup\n' >&2; exit 5; }

args=(artifact finalize-vector --region="${REGION}" --yyyymmdd="${YYYYMMDD}"
  --role="${ROLE}" --workdir="${WORKDIR}" --activation="${ACTIVATION}")
[[ -n "${SESSION}" ]] && args+=(--session="${SESSION}")
[[ -n "${BUNDLE_ID}" ]] && args+=(--bundle-id="${BUNDLE_ID}")

PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${PYTHON}" -m huavd_map_build "${args[@]}"
