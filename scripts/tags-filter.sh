#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

INPUT=""
LAYERS="all"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --input=*) INPUT="${arg#*=}" ;;
    --layers=*) LAYERS="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --input=<pbf> --region=<id> [--layers=all|layer[,layer...]] [--workdir=<path>] [--yyyymm=YYYYMM]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars

[[ -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "--input is required"
INPUT="$(resolve_workspace_path "${INPUT}")"
require_file "${INPUT}"
load_selected_layers SELECTED_LAYERS "${LAYERS}"
require_cmd osmium

cache_dir="$(tags_filter_cache_dir)"
ensure_dir "${cache_dir}"
slug="$(region_slug_configured "${REGION}")"

for layer in "${SELECTED_LAYERS[@]}"; do
  mapfile -t filters < <(layer_tags_filter_args "${layer}")
  ((${#filters[@]} > 0)) || die "${HUAVD_EXIT_INPUT}" "layer has no tags_filter: ${layer}"
  output="${cache_dir}/${slug}-${layer}.osm.pbf"
  log_info "osmium tags-filter ${layer} -> ${output}"
  osmium tags-filter -O -o "${output}" "${INPUT}" "${filters[@]}" \
    || die "${HUAVD_EXIT_ERROR}" "osmium tags-filter failed for layer ${layer}"
done

log_info "tags-filter OK: ${cache_dir}"
