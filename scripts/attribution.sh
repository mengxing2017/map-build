#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

WORKDIR="${WORKDIR:-${HUAVD_MAP_BUILD_HOME:-/tmp/huavd-map-build}}"
REGION="${REGION:-china/guangxi}"
YYYYMMDD="${YYYYMMDD:-$(date -u +%Y%m%d)}"
ROLE="${ROLE:-}"
SESSION="${SESSION:-}"

for arg in "$@"; do
  case "${arg}" in
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --region=*) REGION="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}"; SESSION="" ;;
    --session=*) SESSION="${arg#*=}" ;;
    --role=*) ROLE="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building|raster_bake> [--workdir=<path>] [--yyyymmdd=YYYYMMDD] [--session=<id>]\n' "$0"
      exit 0
      ;;
    *)
      printf 'ERROR: unknown argument: %s\n' "${arg}" >&2
      exit 2
      ;;
  esac
done

if [[ -n "${SESSION}" ]]; then
  if [[ ! "${SESSION}" =~ ^[a-z0-9]+(-[a-z0-9]+)*-[0-9]{8}$ ]]; then
    printf 'ERROR: invalid SESSION: %s; expected {region-slug}-{yyyymmdd}\n' "${SESSION}" >&2
    exit 2
  fi
  YYYYMMDD="${SESSION##*-}"
fi

case "${ROLE}" in
  base|building|raster_bake) ;;
  *)
    printf 'ERROR: attribution role must be base, building, or raster_bake\n' >&2
    exit 2
    ;;
esac

python="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${python}" ]]; then
  python="$(command -v python3 || true)"
fi
if [[ -z "${python}" ]]; then
  printf 'ERROR: Python 3 is required; run make setup\n' >&2
  exit 5
fi

export PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}"
session_args=()
if [[ -n "${SESSION}" ]]; then
  session_args=(--session "${SESSION}")
fi
exec "${python}" -m huavd_map_build artifact write-attribution \
  --region "${REGION}" \
  --yyyymmdd "${YYYYMMDD}" \
  --role "${ROLE}" \
  --workdir "${WORKDIR}" "${session_args[@]}" >/dev/null
