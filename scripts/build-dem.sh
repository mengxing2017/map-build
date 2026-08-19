#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

SOURCE_ID=""
INPUT=""
DEM_ENCODING=""
VERTICAL_DATUM=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --source=*) SOURCE_ID="${arg#*=}" ;;
    --input=*) INPUT="${arg#*=}" ;;
    --encoding=*) DEM_ENCODING="${arg#*=}" ;;
    --vertical-datum=*) VERTICAL_DATUM="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --session=<session> [--source=<id>] [--input=<pmtiles|mbtiles|tile-dir>] [--encoding=<encoding>] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq pmtiles sha512sum
require_region "${REGION}"
normalize_session_vars

SOURCE_ID="${SOURCE_ID:-$(dem_region_source_id "${REGION}")}"
[[ -n "${SOURCE_ID}" ]] || die "${HUAVD_EXIT_INPUT}" "DEM source is not configured"
dem_source_json "${SOURCE_ID}" >/dev/null \
  || die "${HUAVD_EXIT_INPUT}" "DEM source is not configured: ${SOURCE_ID}"

DEM_ENCODING="${DEM_ENCODING:-$(dem_source_value "${SOURCE_ID}" output_encoding)}"
DEM_ENCODING="${DEM_ENCODING:-$(dem_default_encoding)}"
dem_allowed_encoding "${DEM_ENCODING}" \
  || die "${HUAVD_EXIT_INPUT}" "DEM encoding is not allowed: ${DEM_ENCODING}"

VERTICAL_DATUM="${VERTICAL_DATUM:-$(dem_source_value "${SOURCE_ID}" vertical_datum)}"
VERTICAL_DATUM="${VERTICAL_DATUM:-unknown}"

if [[ -z "${INPUT}" ]]; then
  staged_dir="$(staging_dir)/dem/source"
  if [[ -d "${staged_dir}" ]]; then
    INPUT="$(find "${staged_dir}" -maxdepth 1 \( -name '*.pmtiles' -o -name '*.mbtiles' \) | sort | head -n 1)"
    [[ -n "${INPUT}" ]] || INPUT="${staged_dir}"
  fi
fi
[[ -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "DEM input is required; run fetch-dem.sh or pass --input"
INPUT="$(resolve_workspace_path "${INPUT}")"

output="$(build_pmtiles_path dem)"
manifest="$(build_manifest_path dem)"
attribution_file="$(build_attribution_path dem)"
ensure_dir "$(outputs_dir)"

case "${INPUT}" in
  *.pmtiles)
    require_file "${INPUT}"
    cp "${INPUT}" "${output}"
    ;;
  *.mbtiles)
    require_file "${INPUT}"
    pmtiles convert "${INPUT}" "${output}" \
      || die "${HUAVD_EXIT_ERROR}" "pmtiles convert failed: ${INPUT}"
    ;;
  *)
    require_dir "${INPUT}"
    pmtiles convert "${INPUT}" "${output}" \
      || die "${HUAVD_EXIT_ERROR}" "pmtiles convert failed: ${INPUT}"
    ;;
esac

tile_type="$(pmtiles_tile_type "${output}")"
case "${tile_type}" in
  2) tile_format="png" ;;
  3) tile_format="jpg" ;;
  4) tile_format="webp" ;;
  5) tile_format="avif" ;;
  *) die "${HUAVD_EXIT_VERIFY}" "DEM PMTiles tile_type must be raster (2,3,4,5), got ${tile_type}" ;;
esac

bounds="$(pmtiles_bounds "${output}")"
center="$(pmtiles_center "${output}")"
min_zoom="$(pmtiles_min_zoom "${output}")"
max_zoom="$(pmtiles_max_zoom "${output}")"
source_id="$(role_source_id "${REGION}" dem)"
[[ -n "${source_id}" ]] \
  || die "${HUAVD_EXIT_INPUT}" "region has no source_id for DEM metadata: ${REGION}"
package_version="$(region_package_version "${REGION}" dem)"
[[ -n "${package_version}" ]] || die "${HUAVD_EXIT_INPUT}" "region has no package_version for DEM metadata: ${REGION}"
attribution="$(dem_source_value "${SOURCE_ID}" attribution)"
data_license="$(dem_source_value "${SOURCE_ID}" data_license)"
attribution="${attribution:-TBD by licensed DEM provider}"
data_license="${data_license:-TBD}"

metadata_path="$(staging_dir)/metadata.dem.json"
ensure_dir "$(dirname -- "${metadata_path}")"
jq -n \
  --arg name "$(artifact_stem dem)" \
  --argjson bounds "${bounds}" \
  --argjson center "${center}" \
  --argjson minzoom "${min_zoom}" \
  --argjson maxzoom "${max_zoom}" \
  --arg attribution "${attribution}" \
  --arg tile_format "${tile_format}" \
  --arg source_id "${source_id}" \
  --arg encoding "${DEM_ENCODING}" \
  --arg vertical_datum "${VERTICAL_DATUM}" \
  --arg region "${REGION}" \
  --arg data_license "${data_license}" \
  --arg build_time "$(timestamp_utc)" \
  '{
    name: $name,
    format: $tile_format,
    bounds: $bounds,
    center: $center,
    minzoom: $minzoom,
    maxzoom: $maxzoom,
    attribution: $attribution,
    "huavd:source-id": $source_id,
    "huavd:asset-role": "dem-raster",
    "dem-encoding": $encoding,
    "huavd:dem-encoding": $encoding,
    "huavd:vertical-datum": $vertical_datum,
    "huavd:region": $region,
    "huavd:data-license": $data_license,
    "huavd:build-time": $build_time
  }' > "${metadata_path}"

pmtiles edit "${output}" --metadata="${metadata_path}" \
  || die "${HUAVD_EXIT_ERROR}" "pmtiles metadata edit failed: ${output}"

write_sha512_file "${output}"
sha512="$(sha512_value "${output}")"
size_bytes="$(stat -c %s "${output}")"

jq -n \
  --arg build_id "$(timestamp_utc)" \
  --arg region "${REGION}" \
  --arg source_id "${source_id}" \
  --arg package_version "${package_version}" \
  --arg sha512 "${sha512}" \
  --arg path "$(relative_output_path "${output}")" \
  --argjson size_bytes "${size_bytes}" \
  --argjson tile_range "$(jq -n --argjson min_zoom "${min_zoom}" --argjson max_zoom "${max_zoom}" --argjson bounds "${bounds}" '{min_zoom:$min_zoom,max_zoom:$max_zoom,bounds:$bounds}')" \
  --arg dem_encoding "${DEM_ENCODING}" \
  --arg vertical_datum "${VERTICAL_DATUM}" \
  --arg data_license "${data_license}" \
  --arg attribution "${attribution}" \
  '{
    build_id: $build_id,
    region: $region,
    output: {
      path: $path,
      size_bytes: $size_bytes,
      sha512: $sha512,
      tile_range: $tile_range
    },
    huavd_record: {
      id: ($source_id + "-" + $package_version + "-dem"),
      name: ("DEM " + $region + " " + $package_version),
      source_id: $source_id,
      package_version: $package_version,
      source_revision: null,
      asset_role: "dem-raster",
      source_type: "dem",
      format: "pmtiles",
      coord_system: "EPSG:3857",
      transport: "offline",
      style_id: "osm-dev",
      dem_encoding: $dem_encoding,
      vertical_datum: $vertical_datum,
      data_license: $data_license,
      attribution: $attribution
    }
  }' > "${manifest}"

jq -n \
  --arg data_license "${data_license}" \
  --arg attribution "${attribution}" \
  --arg source_id "${SOURCE_ID}" \
  '{data_license:$data_license,attribution:$attribution,sources:[{vendor:$source_id}]}' \
  > "${attribution_file}"

log_info "DEM build OK: ${output}"
