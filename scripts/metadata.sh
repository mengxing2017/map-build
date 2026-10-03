#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

PMTILES=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --pmtiles=*) PMTILES="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --pmtiles=<path> --region=<id> --role=<base|building|raster_bake> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd pmtiles jq sha512sum
require_region "${REGION}"
normalize_session_vars
[[ "${ROLE}" == "base" || "${ROLE}" == "building" || "${ROLE}" == "raster_bake" ]] \
  || die "${HUAVD_EXIT_INPUT}" "metadata role must be base, building, or raster_bake"

[[ -n "${PMTILES}" ]] || PMTILES="$(build_pmtiles_path "${ROLE}")"
PMTILES="$(resolve_workspace_path "${PMTILES}")"
require_file "${PMTILES}"

tile_type="$(pmtiles_tile_type "${PMTILES}")"
format="pbf"
raster_bake=false
tile_count="null"
if [[ "${ROLE}" == "raster_bake" ]]; then
  expected_tile_type="$(jq -r '.raster_bake.tile_type' "$(tippecanoe_json)")"
  expected_tile_compression="$(jq -r '.raster_bake.tile_compression' "$(tippecanoe_json)")"
  [[ "${tile_type}" == "${expected_tile_type}" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "raster_bake PMTiles tile_type must be ${expected_tile_type} (WebP), got ${tile_type}"
  [[ "$(pmtiles_tile_compression "${PMTILES}")" == "${expected_tile_compression}" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "raster_bake PMTiles tile_compression must be ${expected_tile_compression}, got $(pmtiles_tile_compression "${PMTILES}")"
  format="webp"
  raster_bake=true
  tile_count="$(pmtiles_addressed_tiles_count "${PMTILES}")"
else
  [[ "${tile_type}" == "1" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "PMTiles tile_type must be 1 (MVT), got ${tile_type}"
fi

min_zoom="$(pmtiles_min_zoom "${PMTILES}")"
max_zoom="$(pmtiles_max_zoom "${PMTILES}")"
bounds="$(pmtiles_bounds "${PMTILES}")"
center="$(pmtiles_center "${PMTILES}")"
if [[ "${ROLE}" == "raster_bake" ]]; then
  vector_layers='[]'
  build_profile=""
else
  vector_layers="$(effective_vector_layers_json "${REGION}" "${ROLE}" "${max_zoom}")"
  build_profile="$(effective_build_profile "${REGION}" "${ROLE}")"
fi
build_profile_schema="null"
if [[ -n "${build_profile}" ]]; then
  build_profile_schema="$(tier_profile_schema_version)"
fi
source_id="$(role_source_id "${REGION}" "${ROLE}")"
asset_role="$(role_asset_role "${ROLE}")"
available_locales="$(available_locales_json)"
style_locales="$(style_locales_json)"

[[ -n "${source_id}" ]] \
  || die "${HUAVD_EXIT_INPUT}" "region has no source_id for metadata: ${REGION}"

metadata_path="$(staging_dir)/metadata.${ROLE}.json"
ensure_dir "$(dirname -- "${metadata_path}")"

jq -n \
  --arg name "$(artifact_stem "${ROLE}")" \
  --arg format "${format}" \
  --argjson bounds "${bounds}" \
  --argjson center "${center}" \
  --argjson minzoom "${min_zoom}" \
  --argjson maxzoom "${max_zoom}" \
  --arg attribution "© OpenStreetMap contributors" \
  --argjson vector_layers "${vector_layers}" \
  --arg source_id "${source_id}" \
  --arg asset_role "${asset_role}" \
  --argjson available_locales "${available_locales}" \
  --argjson style_locales "${style_locales}" \
  --arg build_time "$(timestamp_utc)" \
  --arg region "${REGION}" \
  --arg build_profile "${build_profile}" \
  --argjson build_profile_schema "${build_profile_schema}" \
  --argjson raster_bake "${raster_bake}" \
  --argjson tile_count "${tile_count}" \
  '{
    name: $name,
    format: $format,
    bounds: $bounds,
    center: $center,
    minzoom: $minzoom,
    maxzoom: $maxzoom,
    attribution: $attribution,
    vector_layers: $vector_layers,
    "huavd:source-id": $source_id,
    "huavd:asset-role": $asset_role,
    "huavd:available-locales": $available_locales,
    "huavd:style-locales": $style_locales,
    "huavd:build-time": $build_time,
    "huavd:region": $region,
    "huavd:data-license": "ODbL-1.0"
  }
  + (if $build_profile == "" then {} else {
      "huavd:build-profile": $build_profile,
      "huavd:build-profile-schema": $build_profile_schema
    } end)
  + (if $raster_bake then {
      "huavd:tile-count": $tile_count,
      "huavd:raster-encoding": "webp"
    } else {} end)' > "${metadata_path}"

log_info "pmtiles edit metadata -> ${PMTILES}"
pmtiles edit "${PMTILES}" --metadata="${metadata_path}" \
  || die "${HUAVD_EXIT_ERROR}" "pmtiles metadata edit failed: ${PMTILES}"

write_sha512_file "${PMTILES}"
log_info "metadata OK: ${metadata_path}"
