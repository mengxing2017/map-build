#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd osmium jq; overview_validate "${OVERVIEW}"
stage="$(overview_staging_dir "${OVERVIEW}" "${YYYYMMDD}")"; cache="$(overview_filter_cache_dir "${OVERVIEW}")/$(sha512_value "${stage}/source.osm.pbf")"; ensure_dir "${stage}/layers"; ensure_dir "${stage}/export-config"
while IFS= read -r layer; do
  cp "${CONFIG_DIR}/export-config/${layer}.json" "${stage}/export-config/${layer}.json"
  export_args=()
  [[ "$(layer_export_keep_untagged "${layer}")" == "true" ]] && export_args+=("--keep-untagged")
  osmium export "${export_args[@]}" -c "${stage}/export-config/${layer}.json" -f geojsonseq -O -o "${stage}/layers/${layer}.geojsonseq" "${cache}/${layer}.osm.pbf" \
    || die "${HUAVD_EXIT_ERROR}" "export failed for ${layer}"
done < <(overview_layers "${OVERVIEW}")
