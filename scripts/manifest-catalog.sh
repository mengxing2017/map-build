#!/usr/bin/env bash

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd -- "${script_dir}/.." && pwd)"
python="${HUAVD_MAP_BUILD_PYTHON:-${repo_dir}/.venv/bin/python}"
if [[ ! -x "${python}" ]]; then
  python="$(command -v python3 || true)"
fi
[[ -n "${python}" ]] || { printf 'Python 3 is required; run make setup\n' >&2; exit 5; }

PYTHONPATH="${repo_dir}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
  exec "${python}" -m huavd_map_build catalog snapshot \
    --config="${CONFIG_PATH:-${repo_dir}/config/regions.yaml}" \
    --output="${OUTPUT:-${repo_dir}/config/derived/catalog.json}"
