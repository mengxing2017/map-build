#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/pmtiles.sh"
source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd jq pmtiles sha512sum; overview_validate "${OVERVIEW}"
pmtiles="$(overview_pmtiles_path "${OVERVIEW}" "${YYYYMMDD}")"; require_file "${pmtiles}"; max_zoom="$(pmtiles_max_zoom "${pmtiles}")"; metadata="$(overview_staging_dir "${OVERVIEW}" "${YYYYMMDD}")/metadata.json"; ensure_dir "$(dirname "${metadata}")"
jq -n --arg name "$(overview_stem "${OVERVIEW}" "${YYYYMMDD}")" --argjson bounds "$(pmtiles_bounds "${pmtiles}")" --argjson center "$(pmtiles_center "${pmtiles}")" --argjson minzoom "$(pmtiles_min_zoom "${pmtiles}")" --argjson maxzoom "${max_zoom}" --argjson vector_layers "$(overview_vector_layers_json "${OVERVIEW}" "${max_zoom}")" --arg source_id "$(overview_get huavd.source_id "${OVERVIEW}")" --arg build_time "$(timestamp_utc)" --arg overview "${OVERVIEW}" '{name:$name,format:"pbf",bounds:$bounds,center:$center,minzoom:$minzoom,maxzoom:$maxzoom,attribution:"© OpenStreetMap contributors",vector_layers:$vector_layers,"huavd:source-id":$source_id,"huavd:asset-role":"overview-vector","huavd:build-time":$build_time,"huavd:overview":$overview,"huavd:data-license":"ODbL-1.0"}' > "${metadata}"
pmtiles edit "${pmtiles}" --metadata="${metadata}" || die "${HUAVD_EXIT_ERROR}" "PMTiles metadata edit failed"; write_sha512_file "${pmtiles}"
