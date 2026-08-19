#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

LAYERS="all"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --layers=*) LAYERS="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--layers=all|layer[,layer...]] [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars
load_selected_layers SELECTED_LAYERS "${LAYERS}"

slug="$(region_slug_configured "${REGION}")"
cache_dir="$(tags_filter_cache_dir)"
stage_export_config="$(export_config_staging_dir)"
stage_layers="$(layers_dir)"
ensure_dir "${stage_export_config}"
ensure_dir "${stage_layers}"

for layer in "${SELECTED_LAYERS[@]}"; do
  source_config="${CONFIG_DIR}/export-config/${layer}.json"
  input="${cache_dir}/${slug}-${layer}.osm.pbf"
  require_file "${source_config}"
  require_file "${input}"
done

require_cmd osmium

for layer in "${SELECTED_LAYERS[@]}"; do
  source_config="${CONFIG_DIR}/export-config/${layer}.json"
  staged_config="${stage_export_config}/${layer}.json"
  input="${cache_dir}/${slug}-${layer}.osm.pbf"
  output="${stage_layers}/${layer}.geojsonseq"
  cp "${source_config}" "${staged_config}"

  log_info "osmium export ${layer} -> ${output}"
  osmium export -c "${staged_config}" -f geojsonseq -O -o "${output}" "${input}" \
    || die "${HUAVD_EXIT_ERROR}" "osmium export failed for layer ${layer}"
done

log_info "export OK: ${stage_layers}"
