#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd jq tippecanoe; overview_validate "${OVERVIEW}"
params="$(overview_params "${OVERVIEW}")"; stage="$(overview_layers_dir "${OVERVIEW}" "${YYYYMMDD}")"; output="$(overview_pmtiles_path "${OVERVIEW}" "${YYYYMMDD}")"; ensure_dir "$(dirname "${output}")"
args=(-Z"$(jq -r .min_zoom <<< "${params}")" -z"$(jq -r .max_zoom <<< "${params}")" --maximum-tile-bytes="$(jq -r .maximum_tile_bytes <<< "${params}")" --name="$(overview_stem "${OVERVIEW}" "${YYYYMMDD}")" --attribution='© OpenStreetMap contributors' --output="${output}")
for key in drop_densest_as_needed extend_zooms_if_still_dropping detect_shared_borders coalesce_densest_as_needed read_parallel; do [[ "$(jq -r ".${key}" <<< "${params}")" == true ]] && args+=("--${key//_/-}"); done
while IFS= read -r layer; do require_file "${stage}/${layer}.geojsonseq"; args+=(-L "${layer}:${stage}/${layer}.geojsonseq"); done < <(overview_layers "${OVERVIEW}")
tippecanoe "${args[@]}" || die "${HUAVD_EXIT_ERROR}" "tippecanoe failed for overview ${OVERVIEW}"
