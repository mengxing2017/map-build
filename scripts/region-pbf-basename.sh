#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

region="${1:-${REGION:-}}"
if [[ -z "${region}" ]]; then
  printf 'ERROR: region is required\n' >&2
  exit 2
fi

python="${HUAVD_MAP_BUILD_PYTHON:-${REPO_ROOT}/.venv/bin/python}"
if [[ ! -x "${python}" ]]; then
  python="$(command -v python3 || true)"
fi
if [[ -z "${python}" ]]; then
  printf 'ERROR: Python 3 is required; run make setup\n' >&2
  exit 5
fi

export PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}"
exec "${python}" -m huavd_map_build catalog pbf-basename "${region}"
