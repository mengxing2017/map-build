#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building> [--workdir=<path>] [--yyyymm=YYYYMM]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars
[[ "${ROLE}" == "base" || "${ROLE}" == "building" ]] \
  || die "${HUAVD_EXIT_INPUT}" "tippecanoe role must be base or building"

params="$(tippecanoe_resolve "${REGION}" "${ROLE}")"
min_zoom="$(jq -r '.min_zoom' <<< "${params}")"
max_zoom="$(jq -r '.max_zoom' <<< "${params}")"
tile_bytes="$(jq -r '.maximum_tile_bytes' <<< "${params}")"
attribution="$(jq -r '.attribution // "© OpenStreetMap contributors"' <<< "${params}")"

stage_layers="$(layers_dir)"
out_dir="$(outputs_dir)"
ensure_dir "${out_dir}"
pmtiles="$(build_pmtiles_path "${ROLE}")"

args=(
  "-Z${min_zoom}"
  "-z${max_zoom}"
  "--maximum-tile-bytes=${tile_bytes}"
  "--name=$(artifact_stem "${ROLE}")"
  "--attribution=${attribution}"
  "--output=${pmtiles}"
)

[[ "$(jq -r '.drop_densest_as_needed' <<< "${params}")" == "true" ]] && args+=("--drop-densest-as-needed")
[[ "$(jq -r '.extend_zooms_if_still_dropping' <<< "${params}")" == "true" ]] && args+=("--extend-zooms-if-still-dropping")
[[ "$(jq -r '.detect_shared_borders' <<< "${params}")" == "true" ]] && args+=("--detect-shared-borders")
[[ "$(jq -r '.coalesce_densest_as_needed' <<< "${params}")" == "true" ]] && args+=("--coalesce-densest-as-needed")
[[ "$(jq -r '.read_parallel' <<< "${params}")" == "true" ]] && args+=("--read-parallel")
[[ "$(jq -r '.no_tile_size_limit' <<< "${params}")" == "true" ]] && args+=("--no-tile-size-limit")
[[ "$(jq -r '.force_feature_limit' <<< "${params}")" == "true" ]] && args+=("--force-feature-limit")

while IFS= read -r layer; do
  layer_file="${stage_layers}/${layer}.geojsonseq"
  require_file "${layer_file}"
  args+=("-L" "${layer}:${layer_file}")
done < <(role_layers "${ROLE}")

require_cmd tippecanoe
log_info "tippecanoe ${ROLE} -> ${pmtiles}"
tippecanoe "${args[@]}" \
  || die "${HUAVD_EXIT_ERROR}" "tippecanoe failed for role ${ROLE}"

log_info "tippecanoe OK: ${pmtiles}"
