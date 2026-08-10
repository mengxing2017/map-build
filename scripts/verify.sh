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
      printf 'usage: %s --region=<id> --role=<base|building|both> [--yyyymm=YYYYMM] [--session=<session>] [--strict]\n' "$0"
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
        verify_label_config_fields
        verify_label_metadata_fields "${metadata}"
        verify_base_fill_config_fields
        verify_base_fill_metadata_fields "${metadata}"
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

verified_any=0
while IFS= read -r role; do
  if [[ "${ROLE}" == "both" && ! -f "$(build_pmtiles_path "${role}")" && "${role}" == "building" ]]; then
    log_warn "skip missing optional building role"
    continue
  fi
  verify_role "${role}"
  verified_any=1
done < <(role_list "${ROLE}")

(( verified_any == 1 )) || die "${HUAVD_EXIT_INPUT}" "no artifacts found to verify for role=${ROLE}"

if ((FAILURES == 0)); then
  printf 'verify: PASS\n'
else
  printf 'verify: FAIL (%d)\n' "${FAILURES}"
  exit "${HUAVD_EXIT_VERIFY}"
fi
