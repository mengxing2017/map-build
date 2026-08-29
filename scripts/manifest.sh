#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq sha512sum stat
require_region "${REGION}"
normalize_session_vars
[[ "${ROLE}" == "base" || "${ROLE}" == "building" ]] \
  || die "${HUAVD_EXIT_INPUT}" "manifest role must be base or building"

pmtiles="$(build_pmtiles_path "${ROLE}")"
require_file "${pmtiles}"
manifest="$(build_manifest_path "${ROLE}")"
ensure_dir "$(dirname -- "${manifest}")"

min_zoom="$(pmtiles_min_zoom "${pmtiles}")"
max_zoom="$(pmtiles_max_zoom "${pmtiles}")"
bounds="$(pmtiles_bounds "${pmtiles}")"
sha512="$(sha512_value "${pmtiles}")"
size_bytes="$(stat -c %s "${pmtiles}")"
source_file="$(staging_dir)/source.osm.pbf"
pbf_url="$(region_pbf_url "${REGION}")"
pbf_basename="$(region_pbf_basename "${REGION}")"
mirror_md5="$(mirror_dir)/${pbf_basename}.md5"
source_size="null"
downloaded_at="null"
md5_value="null"

if [[ -e "${source_file}" ]]; then
  source_size="$(stat -Lc %s "${source_file}" 2>/dev/null || printf 'null')"
  downloaded_at="$(date -u -r "${source_file}" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf 'null')"
fi
if [[ -f "${mirror_md5}" ]]; then
  parsed_md5="$(awk '{print $1; exit}' "${mirror_md5}")"
  if [[ -n "${parsed_md5}" ]]; then
    md5_value="${parsed_md5}"
  fi
fi

tools_osmium="$(cmd_version osmium)"
tools_tippecanoe="$(cmd_version tippecanoe)"
tools_pmtiles="$(cmd_version pmtiles)"
tippecanoe_params="$(effective_tippecanoe_resolve "${REGION}" "${ROLE}")"
vector_layer_names="$(effective_role_layers_json "${REGION}" "${ROLE}")"
build_profile="$(effective_build_profile "${REGION}" "${ROLE}")"
build_profile_schema="null"
if [[ -n "${build_profile}" ]]; then
  build_profile_schema="$(tier_profile_schema_version)"
fi
package_version="$(region_package_version "${REGION}" "${ROLE}")"
source_id="$(role_source_id "${REGION}" "${ROLE}")"
asset_role="$(role_asset_role "${ROLE}")"
source_type="$(role_source_type "${ROLE}")"
source_revision="geofabrik-$(region_basename "${REGION}")-$(yyyymmdd_dash "${YYYYMMDD}")"
style_id="$(region_style_id "${REGION}")"
artifact_name="${SESSION}.${ROLE}"
offline_map_id="$(region_stable_id "${REGION}")"
[[ -n "${offline_map_id}" && "${offline_map_id}" != "null" ]] \
  || die "${HUAVD_EXIT_INPUT}" "region has no huavd.region_id for manifest id: ${REGION}"
bundle_id="${HUAVD_MAP_BUNDLE_ID:-$(region_slug)-${YYYYMMDD}-standard}"
activation="${HUAVD_MAP_ACTIVATION:-manual}"
build_id="$(timestamp_utc)"
available_locales="$(available_locales_json)"
style_locales="$(style_locales_json)"

jq -n \
  --arg schema "huavd-map-build/v1" \
  --arg region "${REGION}" \
  --arg yyyymmdd "${YYYYMMDD}" \
  --arg build_id "${build_id}" \
  --arg source_url "${pbf_url}" \
  --argjson source_size "${source_size}" \
  --arg downloaded_at "${downloaded_at}" \
  --arg md5 "${md5_value}" \
  --arg osmium_version "${tools_osmium}" \
  --arg tippecanoe_version "${tools_tippecanoe}" \
  --arg pmtiles_version "${tools_pmtiles}" \
  --argjson tippecanoe "${tippecanoe_params}" \
  --arg output_path "$(relative_output_path "${pmtiles}")" \
  --argjson output_size "${size_bytes}" \
  --arg sha512 "${sha512}" \
  --argjson min_zoom "${min_zoom}" \
  --argjson max_zoom "${max_zoom}" \
  --argjson bounds "${bounds}" \
  --argjson vector_layers "${vector_layer_names}" \
  --arg build_profile "${build_profile}" \
  --argjson build_profile_schema "${build_profile_schema}" \
  --arg source_id "${source_id}" \
  --arg asset_role "${asset_role}" \
  --arg source_type "${source_type}" \
  --arg package_version "${package_version}" \
  --arg source_revision "${source_revision}" \
  --arg style_id "${style_id}" \
  --arg artifact_name "${artifact_name}" \
  --arg offline_map_id "${offline_map_id}" \
  --arg bundle_id "${bundle_id}" \
  --arg activation "${activation}" \
  --arg released_at "${build_id}" \
  --argjson available_locales "${available_locales}" \
  --argjson style_locales "${style_locales}" \
  '{
    schema: $schema,
    region: $region,
    yyyymmdd: $yyyymmdd,
    build_id: $build_id,
    source: {
      vendor: "geofabrik",
      url: $source_url,
      downloaded_at: (if $downloaded_at == "null" then null else $downloaded_at end),
      size_bytes: $source_size,
      md5: (if $md5 == "null" then null else $md5 end),
      osm_timestamp: null
    },
    tools: {
      osmium: $osmium_version,
      tippecanoe: $tippecanoe_version,
      pmtiles: $pmtiles_version,
      "huavd-map-build": "shell"
    },
    tippecanoe: $tippecanoe,
    output: {
      path: $output_path,
      size_bytes: $output_size,
      sha512: $sha512,
      tile_range: {
        min_zoom: $min_zoom,
        max_zoom: $max_zoom,
        bounds: $bounds
      }
    },
    vector_layers: $vector_layers,
    huavd_record: {
      id: $offline_map_id,
      name: $artifact_name,
      source_id: $source_id,
      asset_role: $asset_role,
      source_type: $source_type,
      package_version: $package_version,
      source_revision: $source_revision,
      transport: "offline",
      coord_system: "EPSG:3857",
      style_id: $style_id,
      format: "pmtiles",
      available_locales: $available_locales,
      style_locales: $style_locales,
      released_at: $released_at,
      activation: $activation,
      bundle_id: $bundle_id
    },
    license: {
      data_license: "ODbL-1.0",
      attribution: "© OpenStreetMap contributors"
    }
  }
  + (if $build_profile == "" then {} else {
      build_profile: {name: $build_profile, schema_version: $build_profile_schema}
    } end)' > "${manifest}"

log_info "manifest OK: ${manifest}"
