#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

STRICT=0

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --strict) STRICT=1 ;;
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building|both|dem|all> [--yyyymm=YYYYMM] [--session=<session>] [--strict]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq sha512sum stat
ROLE="${ROLE:-base}"
if [[ -n "${SESSION}" ]]; then
  validate_session "${SESSION}"
  YYYYMM="$(session_yyyymm "${SESSION}")"
  inferred_region="$(region_id_from_slug "$(session_region_slug "${SESSION}")")"
  if [[ -n "${inferred_region}" ]]; then
    REGION="${inferred_region}"
  fi
fi
require_region "${REGION}"
normalize_session_vars

FAILURES=0

ok() {
  printf 'OK   %s\n' "$*"
}

fail() {
  printf 'FAIL %s\n' "$*"
  FAILURES=$((FAILURES + 1))
}

check_eq() {
  local label="$1"
  local actual="$2"
  local expected="$3"
  if [[ "${actual}" == "${expected}" ]]; then
    ok "${label}"
  else
    fail "${label}: expected ${expected}, got ${actual}"
  fi
}

check_metadata_layer_field() {
  local metadata="$1"
  local layer_id="$2"
  local field="$3"
  if jq -e --arg layer "${layer_id}" --arg field "${field}" '
    .vector_layers[] | select(.id == $layer) | .fields[$field]
  ' >/dev/null <<< "${metadata}"; then
    ok "metadata layer=${layer_id} field=${field}"
  else
    fail "metadata layer=${layer_id} missing field=${field}"
  fi
}

check_metadata_layer_minzoom() {
  local metadata="$1"
  local layer_id="$2"
  local expected="$3"
  local actual
  actual="$(jq -r --arg layer "${layer_id}" '
    .vector_layers[] | select(.id == $layer) | .minzoom
  ' <<< "${metadata}")"
  check_eq "metadata layer=${layer_id} minzoom" "${actual}" "${expected}"
}

verify_label_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "place_label" "place"
  check_metadata_layer_field "${metadata}" "poi_label" "amenity"
  check_metadata_layer_field "${metadata}" "poi_label" "shop"
  check_metadata_layer_field "${metadata}" "poi_label" "tourism"
  check_metadata_layer_field "${metadata}" "transport_label" "public_transport"
}

check_config_final_field_in_include_tags() {
  local layer_id="$1"
  local field="$2"
  if jq -e --arg layer "${layer_id}" --arg field "${field}" '
    (.source_layers[$layer].include_tags // []) | index($field)
  ' "$(layers_json)" >/dev/null; then
    ok "config layer=${layer_id} include_tags has ${field}"
  else
    fail "config layer=${layer_id} final field ${field} missing from include_tags"
  fi
}

check_config_final_field() {
  local layer_id="$1"
  local field="$2"
  if jq -e --arg layer "${layer_id}" --arg field "${field}" '
    .source_layers[$layer].final_fields[$field]
  ' "$(layers_json)" >/dev/null; then
    ok "config layer=${layer_id} final_fields has ${field}"
  else
    fail "config layer=${layer_id} final_fields missing ${field}"
  fi
}

verify_name_locale_config_fields() {
  local layer_id
  if jq -e '
    .global.name_coalesce_order == ["name:zh-Hans", "name:zh", "name", "name:en"]
  ' "$(layers_json)" >/dev/null; then
    ok "config global.name_coalesce_order zh before name before en"
  else
    fail "config global.name_coalesce_order must be name:zh-Hans, name:zh, name, name:en"
  fi
  for layer_id in road railway water waterway landuse building admin natural_a leisure_a place_label poi_label transport_label; do
    check_config_final_field_in_include_tags "${layer_id}" "name:zh"
    check_config_final_field "${layer_id}" "name:zh"
  done
}

verify_label_config_fields() {
  check_config_final_field_in_include_tags "place_label" "place"
  check_config_final_field_in_include_tags "poi_label" "amenity"
  check_config_final_field_in_include_tags "poi_label" "shop"
  check_config_final_field_in_include_tags "poi_label" "tourism"
  check_config_final_field_in_include_tags "transport_label" "public_transport"
}

verify_base_fill_config_fields() {
  check_config_final_field_in_include_tags "landuse" "landuse"
  check_config_final_field_in_include_tags "natural_a" "natural"
  check_config_final_field_in_include_tags "leisure_a" "leisure"
  check_config_final_field_in_include_tags "building" "building"
}

verify_base_fill_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "landuse" "landuse"
  check_metadata_layer_field "${metadata}" "natural_a" "natural"
  check_metadata_layer_field "${metadata}" "leisure_a" "leisure"
  check_metadata_layer_field "${metadata}" "building" "building"
  check_metadata_layer_minzoom "${metadata}" "building" "12"
}

verify_railway_config_fields() {
  check_config_final_field_in_include_tags "railway" "railway"
}

verify_railway_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "railway" "railway"
  check_metadata_layer_field "${metadata}" "railway" "bridge"
  check_metadata_layer_field "${metadata}" "railway" "tunnel"
}

verify_role() {
  local role="$1"
  local pmtiles manifest sha_file metadata header_bounds metadata_bounds expected_layers actual_layers actual_sha manifest_sha file_sha manifest_size stat_size
  pmtiles="$(build_pmtiles_path "${role}")"
  manifest="$(build_manifest_path "${role}")"
  sha_file="$(build_sha512_path "${role}")"

  require_file "${pmtiles}"
  require_file "${manifest}"
  require_file "${sha_file}"
  require_cmd pmtiles

  printf 'verify role=%s file=%s\n' "${role}" "${pmtiles}"

  check_eq "pmtiles magic" "$(pmtiles_magic "${pmtiles}")" "PMTiles"
  check_eq "pmtiles spec_version" "$(pmtiles_spec_version "${pmtiles}")" "3"
  check_eq "pmtiles internal_compression gzip" "$(pmtiles_internal_compression "${pmtiles}")" "2"
  check_eq "pmtiles tile_compression gzip" "$(pmtiles_tile_compression "${pmtiles}")" "2"
  check_eq "pmtiles tile_type MVT" "$(pmtiles_tile_type "${pmtiles}")" "1"

  root_offset="$(pmtiles_root_offset "${pmtiles}")"
  root_length="$(pmtiles_root_length "${pmtiles}")"
  if (( root_offset + root_length <= 16384 )); then
    ok "root directory within 16 KiB range"
  else
    fail "root directory too large: offset=${root_offset} length=${root_length}"
  fi

  stat_size="$(stat -c %s "${pmtiles}")"
  manifest_size="$(jq -r '.output.size_bytes' "${manifest}")"
  check_eq "manifest output.size_bytes" "${manifest_size}" "${stat_size}"

  metadata="$(pmtiles_cli_metadata "${pmtiles}")" || fail "pmtiles metadata readable"
  if [[ -n "${metadata}" ]] && jq -e . >/dev/null 2>&1 <<< "${metadata}"; then
    ok "pmtiles metadata JSON"
    expected_layers=12
    [[ "${role}" == "building" ]] && expected_layers=1
    actual_layers="$(jq -r '.vector_layers | length' <<< "${metadata}")"
    check_eq "metadata vector_layers length" "${actual_layers}" "${expected_layers}"
    if jq -e '.attribution | strings | contains("OpenStreetMap contributors")' >/dev/null <<< "${metadata}"; then
      ok "metadata attribution"
    else
      fail "metadata attribution missing OpenStreetMap contributors"
    fi
    check_eq "metadata huavd:data-license" "$(jq -r '."huavd:data-license"' <<< "${metadata}")" "ODbL-1.0"
    if ((STRICT)); then
      jq -e '."huavd:available-locales" | type == "array" and length > 0' >/dev/null <<< "${metadata}" \
        && ok "metadata huavd:available-locales" \
        || fail "metadata huavd:available-locales missing or empty"
      jq -e '."huavd:style-locales" | type == "array" and length > 0' >/dev/null <<< "${metadata}" \
        && ok "metadata huavd:style-locales" \
        || fail "metadata huavd:style-locales missing or empty"
      if [[ "${role}" == "base" ]]; then
        verify_name_locale_config_fields
        verify_label_config_fields
        verify_label_metadata_fields "${metadata}"
        verify_base_fill_config_fields
        verify_base_fill_metadata_fields "${metadata}"
        verify_railway_config_fields
        verify_railway_metadata_fields "${metadata}"
      fi
    fi
    header_bounds="$(pmtiles_bounds "${pmtiles}")"
    metadata_bounds="$(jq -c '.bounds' <<< "${metadata}")"
    if jq -n -e --argjson header "${header_bounds}" --argjson meta "${metadata_bounds}" '
      def abs: if . < 0 then -. else . end;
      [0,1,2,3] | map((($header[.] - $meta[.]) | abs) <= 0.0000001) | all
    ' >/dev/null; then
      ok "metadata bounds match PMTiles header"
    else
      fail "metadata bounds mismatch"
    fi
  else
    fail "pmtiles metadata JSON"
  fi

  if ((STRICT)); then
    style_file="$(build_style_path)"
    if [[ -f "${style_file}" ]]; then
      jq -e '.version == 8 and (.sources | type == "object") and (.glyphs | strings | contains("{fontstack}") and contains("{range}.pbf"))' "${style_file}" >/dev/null \
        && ok "style.json MapLibre glyph template" \
        || fail "style.json is missing MapLibre version/source/glyph template"
    fi

    glyphs_dir="$(build_glyphs_dir)"
    if [[ -d "${glyphs_dir}" ]]; then
      if find "${glyphs_dir}" -type f -name '*.pbf' | grep -q .; then
        ok "glyph pbf files present"
      else
        fail "glyph output directory has no pbf files"
      fi
      if find "${glyphs_dir}" -type f -name '*.pbf.sha512' | grep -q .; then
        ok "glyph sha512 sidecars present"
      else
        fail "glyph output directory has no sha512 sidecars"
      fi
    fi
  fi

  actual_sha="$(sha512_value "${pmtiles}")"
  file_sha="$(awk '{print $1; exit}' "${sha_file}")"
  manifest_sha="$(jq -r '.output.sha512' "${manifest}")"
  check_eq "sha512 sidecar" "${file_sha}" "${actual_sha}"
  check_eq "manifest output.sha512" "${manifest_sha}" "${actual_sha}"

  if ((STRICT)); then
    if header_json="$(pmtiles_cli_header_json "${pmtiles}")" && jq -e . >/dev/null 2>&1 <<< "${header_json}"; then
      ok "pmtiles header-json"
      jq -e '.internal_compression == 2 and .tile_compression == 2 and .tile_type == 1' >/dev/null <<< "${header_json}" \
        && ok "pmtiles header-json compression/type" \
        || fail "pmtiles header-json compression/type"
    else
      fail "pmtiles header-json"
    fi
  fi
}

verify_dem_role() {
  local pmtiles manifest sha_file metadata actual_sha file_sha manifest_sha stat_size manifest_size tile_type header_bounds metadata_bounds header_json
  pmtiles="$(build_pmtiles_path dem)"
  manifest="$(build_manifest_path dem)"
  sha_file="$(build_sha512_path dem)"

  require_file "${pmtiles}"
  require_file "${manifest}"
  require_file "${sha_file}"
  require_cmd pmtiles

  printf 'verify role=dem file=%s\n' "${pmtiles}"

  check_eq "pmtiles magic" "$(pmtiles_magic "${pmtiles}")" "PMTiles"
  check_eq "pmtiles spec_version" "$(pmtiles_spec_version "${pmtiles}")" "3"
  tile_type="$(pmtiles_tile_type "${pmtiles}")"
  case "${tile_type}" in
    2|3|4|5) ok "dem pmtiles tile_type raster" ;;
    *) fail "dem pmtiles tile_type must be raster, got ${tile_type}" ;;
  esac

  stat_size="$(stat -c %s "${pmtiles}")"
  manifest_size="$(jq -r '.output.size_bytes' "${manifest}")"
  check_eq "manifest output.size_bytes" "${manifest_size}" "${stat_size}"

  metadata="$(pmtiles_cli_metadata "${pmtiles}")" || fail "dem metadata readable"
  if [[ -n "${metadata}" ]] && jq -e . >/dev/null 2>&1 <<< "${metadata}"; then
    ok "dem metadata JSON"
    jq -e '."dem-encoding" | IN("mapbox-terrain-rgb","terrarium","heightmap-u16")' >/dev/null <<< "${metadata}" \
      && ok "dem metadata dem-encoding" \
      || fail "dem metadata missing or invalid dem-encoding"
    jq -e '."huavd:vertical-datum" | type == "string" and length > 0' >/dev/null <<< "${metadata}" \
      && ok "dem metadata vertical datum" \
      || fail "dem metadata missing huavd:vertical-datum"
    jq -e '.attribution | type == "string" and length > 0' >/dev/null <<< "${metadata}" \
      && ok "dem metadata attribution" \
      || fail "dem metadata attribution"
    header_bounds="$(pmtiles_bounds "${pmtiles}")"
    metadata_bounds="$(jq -c '.bounds' <<< "${metadata}")"
    if jq -n -e --argjson header "${header_bounds}" --argjson meta "${metadata_bounds}" '
      def abs: if . < 0 then -. else . end;
      [0,1,2,3] | map((($header[.] - $meta[.]) | abs) <= 0.0000001) | all
    ' >/dev/null; then
      ok "dem metadata bounds match PMTiles header"
    else
      fail "dem metadata bounds mismatch"
    fi
  else
    fail "dem metadata JSON"
  fi

  actual_sha="$(sha512_value "${pmtiles}")"
  file_sha="$(awk '{print $1; exit}' "${sha_file}")"
  manifest_sha="$(jq -r '.output.sha512' "${manifest}")"
  check_eq "sha512 sidecar" "${file_sha}" "${actual_sha}"
  check_eq "manifest output.sha512" "${manifest_sha}" "${actual_sha}"

  if ((STRICT)); then
    if header_json="$(pmtiles_cli_header_json "${pmtiles}")" && jq -e . >/dev/null 2>&1 <<< "${header_json}"; then
      ok "dem pmtiles header-json"
      jq -e '.tile_type | IN(2,3,4,5)' >/dev/null <<< "${header_json}" \
        && ok "dem pmtiles header-json tile_type" \
        || fail "dem pmtiles header-json tile_type"
    else
      fail "dem pmtiles header-json"
    fi
  fi
}

verified_any=0
while IFS= read -r role; do
  if [[ "${ROLE}" == "both" && ! -f "$(build_pmtiles_path "${role}")" && "${role}" == "building" ]]; then
    log_warn "skip missing optional building role"
    continue
  fi
  if [[ "${role}" == "dem" ]]; then
    verify_dem_role
  else
    verify_role "${role}"
  fi
  verified_any=1
done < <(role_list "${ROLE}")

(( verified_any == 1 )) || die "${HUAVD_EXIT_INPUT}" "no artifacts found to verify for role=${ROLE}"

if ((FAILURES == 0)); then
  printf 'verify: PASS\n'
else
  printf 'verify: FAIL (%d)\n' "${FAILURES}"
  exit "${HUAVD_EXIT_VERIFY}"
fi
