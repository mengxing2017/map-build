#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; source "${SCRIPT_DIR}/lib/common.sh"; source "${SCRIPT_DIR}/lib/config.sh"; source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd jq; overview_validate "${OVERVIEW}"
sources="$(while IFS= read -r region; do jq -n --arg region "${region}" --arg url "$(region_pbf_url "${region}")" '{vendor:"geofabrik",region:$region,url:$url}'; done < <(overview_source_regions "${OVERVIEW}") | jq -s .)"
jq -n --argjson sources "${sources}" '{data_license:"ODbL-1.0",attribution:"© OpenStreetMap contributors",sources:$sources}' > "$(overview_attribution_path "${OVERVIEW}" "${YYYYMMDD}")"
