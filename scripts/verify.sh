#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"
# shellcheck source=lib/viewport.sh
source "${SCRIPT_DIR}/lib/viewport.sh"

STRICT=0

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --strict) STRICT=1 ;;
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building|raster_bake|base_raster|both_raster|both|dem|all> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--strict]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq stat
ROLE="${ROLE:-base}"
if [[ -n "${SESSION}" ]]; then
  validate_session "${SESSION}"
  YYYYMMDD="$(session_yyyymmdd "${SESSION}")"
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

verify_style_source_layers() {
  local style_file="$1"
  local allowed_layers="$2"
  local unknown
  unknown="$(jq -r --argjson allowed "${allowed_layers}" '
    [.layers[] | .["source-layer"]? | select(. != null) | select($allowed | index(.) | not)] | unique[]
  ' "${style_file}")"
  if [[ -z "${unknown}" ]]; then
    ok "style.json source layers match artifact"
  else
    while IFS= read -r layer; do
      [[ -n "${layer}" ]] && fail "style.json references absent source layer: ${layer}"
    done <<< "${unknown}"
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
  check_metadata_layer_field "${metadata}" "place_label" "admin_id"
  check_metadata_layer_field "${metadata}" "place_label" "boundary_admin_level"
  check_metadata_layer_field "${metadata}" "place_label" "label_tier"
  check_metadata_layer_field "${metadata}" "place_label" "label_rank"
  check_metadata_layer_field "${metadata}" "poi_label" "amenity"
  check_metadata_layer_field "${metadata}" "poi_label" "shop"
  check_metadata_layer_field "${metadata}" "poi_label" "tourism"
  check_metadata_layer_field "${metadata}" "transport_label" "public_transport"
  check_metadata_layer_field "${metadata}" "transport_label" "railway"
  check_metadata_layer_field "${metadata}" "transport_label" "ref"
  check_metadata_layer_field "${metadata}" "transport_label" "network"
  check_metadata_layer_field "${metadata}" "peak" "natural"
  check_metadata_layer_field "${metadata}" "peak" "ele"
  check_metadata_layer_minzoom "${metadata}" "peak" "10"
  check_metadata_layer_field "${metadata}" "highway_point" "highway"
  check_metadata_layer_field "${metadata}" "highway_point" "ref"
  check_metadata_layer_field "${metadata}" "highway_point" "network"
  check_metadata_layer_minzoom "${metadata}" "highway_point" "10"
}

verify_admin_line_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "admin_line" "admin_level"
  check_metadata_layer_field "${metadata}" "admin_line" "admin_tier"
  check_metadata_layer_field "${metadata}" "admin_line" "level_source"
}

verify_staged_admin_line_tiering() {
  local staged report
  staged="$(layers_dir)/admin_line.geojsonseq"
  report="${WORKDIR}/derived/${SESSION}/admin-line-tier-report.json"
  [[ -f "${staged}" ]] || { fail "staged admin_line is missing"; return; }
  [[ -f "${report}" ]] || { fail "admin_line tier report is missing"; return; }

  if jq -e '
    .schema_version == 1
    and (.retained.count | type == "number" and . >= 0)
    and (.retained.id_leak_count == 0)
    and (.relation_sidecar.way_count | type == "number" and . >= 0)
    and (.discarded.by_reason | type == "object")
  ' "${report}" >/dev/null; then
    ok "admin_line tier report"
  else
    fail "admin_line tier report is invalid"
  fi

  if [[ ! -s "${staged}" ]]; then
    ok "staged admin_line is empty"
  elif jq --seq -e '[inputs | ((.properties | has("@id")) | not)] | all' "${staged}" >/dev/null; then
    ok "staged admin_line has no @id"
  else
    fail "staged admin_line leaks @id"
  fi
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

check_config_include_tag() {
  local layer_id="$1"
  local field="$2"
  if jq -e --arg layer "${layer_id}" --arg field "${field}" '
    (.source_layers[$layer].include_tags // []) | index($field)
  ' "$(layers_json)" >/dev/null; then
    ok "config layer=${layer_id} include_tags has ${field}"
  else
    fail "config layer=${layer_id} include_tags missing ${field}"
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

check_export_config_include_tag() {
  local layer_id="$1"
  local field="$2"
  local export_config="${CONFIG_DIR}/export-config/${layer_id}.json"
  if jq -e --arg field "${field}" '
    (.include_tags // []) | index($field)
  ' "${export_config}" >/dev/null; then
    ok "export-config layer=${layer_id} include_tags has ${field}"
  else
    fail "export-config layer=${layer_id} include_tags missing ${field}"
  fi
}

verify_config_final_fields_declared() {
  local mismatch
  mismatch="$(jq -r '
    .source_layers
    | to_entries[]
    | .key as $layer
    | ((.value.include_tags // []) + ((.value.normalize // {}) | keys) + (.value.enrich_fields // [])) as $allowed
    | (.value.final_fields // {})
    | keys[]
    | select($allowed | index(.) | not)
    | "\($layer).\(.): final_fields must be declared by include_tags, normalize, or enrichment"
  ' "$(layers_json)")"
  if [[ -z "${mismatch}" ]]; then
    ok "config final_fields declared by include_tags, normalize, or enrichment"
  else
    while IFS= read -r line; do
      [[ -n "${line}" ]] && fail "${line}"
    done <<< "${mismatch}"
  fi
}

verify_export_config_include_tags() {
  local layer_id export_config expected actual missing extra
  while IFS= read -r layer_id; do
    export_config="${CONFIG_DIR}/export-config/${layer_id}.json"
    require_file "${export_config}"
    expected="$(jq -c --arg layer "${layer_id}" '
      (.source_layers[$layer].include_tags // []) | unique | sort
    ' "$(layers_json)")"
    actual="$(jq -c '(.include_tags // []) | unique | sort' "${export_config}")"
    if [[ "${actual}" == "${expected}" ]]; then
      ok "export-config layer=${layer_id} include_tags match config"
    else
      missing="$(jq -cn --argjson expected "${expected}" --argjson actual "${actual}" '$expected - $actual')"
      extra="$(jq -cn --argjson expected "${expected}" --argjson actual "${actual}" '$actual - $expected')"
      fail "export-config layer=${layer_id} include_tags mismatch: missing=${missing} extra=${extra}"
    fi
  done < <(layers_list)
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
  for layer_id in road railway water waterway landuse building admin natural_a natural_line peak leisure_a place_label poi_label transport_label highway_point island; do
    check_config_final_field_in_include_tags "${layer_id}" "name:zh"
    check_config_final_field "${layer_id}" "name:zh"
  done
}

verify_label_config_fields() {
  check_config_final_field_in_include_tags "place_label" "place"
  check_config_final_field "place_label" "admin_id"
  check_config_final_field "place_label" "boundary_admin_level"
  check_config_final_field "place_label" "label_tier"
  check_config_final_field "place_label" "label_rank"
  check_config_final_field_in_include_tags "poi_label" "amenity"
  check_config_final_field_in_include_tags "poi_label" "shop"
  check_config_final_field_in_include_tags "poi_label" "tourism"
  check_config_layer_tags_filter "poi_label" "a/amenity=hospital"
  check_config_layer_tags_filter "poi_label" "a/amenity=school"
  check_config_layer_tags_filter "poi_label" "w/tourism"
  check_config_layer_tags_filter "poi_label" "a/tourism"
  check_config_final_field_in_include_tags "transport_label" "public_transport"
  check_config_final_field_in_include_tags "transport_label" "railway"
  check_config_final_field_in_include_tags "transport_label" "ref"
  check_config_final_field_in_include_tags "transport_label" "network"
  check_config_final_field "transport_label" "railway"
  check_config_final_field "transport_label" "ref"
  check_config_final_field "transport_label" "network"
  verify_layer_config_fields peak natural ele
  verify_layer_config_fields highway_point highway ref network
}

check_config_layer_tags_filter() {
  local layer_id="$1"
  local filter="$2"
  if jq -e --arg layer "${layer_id}" --arg filter "${filter}" '
    .source_layers[$layer].tags_filter | index($filter)
  ' "$(layers_json)" >/dev/null; then
    ok "config layer=${layer_id} tags_filter=${filter}"
  else
    fail "config layer=${layer_id} missing tags_filter=${filter}"
  fi
}

verify_base_fill_config_fields() {
  check_config_final_field_in_include_tags "landuse" "landuse"
  check_config_final_field_in_include_tags "natural_a" "natural"
  check_config_final_field "natural_a" "natural"
  check_config_final_field_in_include_tags "natural_line" "natural"
  check_config_final_field "natural_line" "natural"
  check_config_final_field_in_include_tags "leisure_a" "leisure"
  check_config_final_field_in_include_tags "building" "building"
}

verify_base_fill_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "landuse" "landuse"
  check_metadata_layer_field "${metadata}" "natural_a" "natural"
  check_metadata_layer_field "${metadata}" "natural_line" "natural"
  check_metadata_layer_field "${metadata}" "leisure_a" "leisure"
  check_metadata_layer_field "${metadata}" "building" "building"
  check_metadata_layer_minzoom "${metadata}" "natural_line" "10"
  check_metadata_layer_minzoom "${metadata}" "building" "12"
}

verify_road_config_fields() {
  check_config_final_field_in_include_tags "road" "ref"
  check_config_final_field "road" "ref"
  check_export_config_include_tag "road" "ref"
  check_config_final_field_in_include_tags "road" "highway"
  check_config_final_field "road" "highway"
  check_export_config_include_tag "road" "highway"
}

verify_road_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "road" "ref"
  check_metadata_layer_field "${metadata}" "road" "highway"
  check_metadata_layer_field "${metadata}" "road" "bridge"
  check_metadata_layer_field "${metadata}" "road" "tunnel"
}

verify_railway_config_fields() {
  check_config_final_field_in_include_tags "railway" "railway"
  check_config_final_field "railway" "railway"
  check_export_config_include_tag "railway" "railway"
  check_config_final_field_in_include_tags "railway" "highspeed"
  check_config_final_field "railway" "highspeed"
  check_export_config_include_tag "railway" "highspeed"
}

verify_railway_metadata_fields() {
  local metadata="$1"
  check_metadata_layer_field "${metadata}" "railway" "railway"
  check_metadata_layer_field "${metadata}" "railway" "highspeed"
  check_metadata_layer_field "${metadata}" "railway" "bridge"
  check_metadata_layer_field "${metadata}" "railway" "tunnel"
}

verify_style_text_layers() {
  local style_file="$1"
  [[ -f "${style_file}" ]] || { fail "style.json missing"; return; }
  for layer_id in road-shield railway-labels island-labels peak-symbol transport-station-symbol highway-point-symbol poi-tourism-symbol poi-amenity-symbol; do
    check_style_layer_present "${style_file}" "${layer_id}"
  done
  check_style_layer_source_layer "${style_file}" "road-shield" "road"
  check_style_layer_layout_contains "${style_file}" "road-shield" "text-field" "ref"
  check_style_layer_filter_contains "${style_file}" "road-shield" "ref"
  check_style_layer_filter_contains "${style_file}" "road-shield" "highway"
  check_style_layer_filter_excludes "${style_file}" "road-shield" "network"
  check_style_layer_filter_excludes "${style_file}" "road-shield" "int_ref"
  check_style_layer_before "${style_file}" "railway" "admin-0-boundary"
  check_style_layer_before "${style_file}" "admin-2-boundary" "peak-symbol"
  for layer_id in admin-0-boundary admin-1-boundary admin-2-boundary; do
    check_style_layer_filter_contains "${style_file}" "${layer_id}" "maritime"
    check_style_layer_filter_contains "${style_file}" "${layer_id}" "yes"
  done
  check_style_layer_filter_contains "${style_file}" "transport-station-symbol" '"station"'
  check_style_layer_filter_contains "${style_file}" "transport-station-symbol" '"halt"'
  check_style_layer_filter_excludes "${style_file}" "transport-station-symbol" '"stop"'
  check_style_layer_icon_image_contains "${style_file}" "transport-station-symbol" "rail-metro"
  check_style_layer_icon_image_contains "${style_file}" "transport-station-symbol" "rail-light"
  check_style_layer_filter_contains "${style_file}" "transport-label" '"stop"'
  check_style_layer_filter_excludes "${style_file}" "highway-point-symbol" "motorway_junction"
  check_style_layer_icon_image_contains "${style_file}" "highway-point-symbol" "services"
  check_style_layer_icon_image_contains "${style_file}" "highway-point-symbol" "rest-area"
  check_style_layer_filter_excludes "${style_file}" "poi-tourism-symbol" '"information"'
  check_style_layer_icon_image_contains "${style_file}" "poi-amenity-symbol" "hospital"
  check_style_layer_icon_image_contains "${style_file}" "poi-amenity-symbol" "school"
  check_style_layer_layout_bool "${style_file}" "highway-point-symbol" "icon-allow-overlap" "true"
  check_style_layer_layout_bool "${style_file}" "highway-point-symbol" "icon-ignore-placement" "true"
  check_style_layer_layout_bool "${style_file}" "poi-amenity-symbol" "icon-allow-overlap" "true"
  check_style_layer_layout_bool "${style_file}" "poi-amenity-symbol" "icon-ignore-placement" "true"
}

check_style_layer_before() {
  local style_file="$1" before="$2" after="$3"
  if jq -e --arg before "${before}" --arg after "${after}" '
    (.layers | map(.id)) as $ids
    | ($ids | index($before)) as $before_index
    | ($ids | index($after)) as $after_index
    | $before_index != null and $after_index != null and $before_index < $after_index
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${before} precedes ${after}"
  else
    fail "style.json layer order must place ${before} before ${after}"
  fi
}

check_style_layer_present() {
  local style_file="$1"
  local layer_id="$2"
  if jq -e --arg id "${layer_id}" '.layers[] | select(.id == $id)' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id}"
  else
    fail "style.json missing layer=${layer_id}"
  fi
}

check_style_layer_source_layer() {
  local style_file="$1"
  local layer_id="$2"
  local source_layer="$3"
  if jq -e --arg id "${layer_id}" --arg source_layer "${source_layer}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | $match["source-layer"] == $source_layer
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} source-layer=${source_layer}"
  else
    fail "style.json layer=${layer_id} source-layer must be ${source_layer}"
  fi
}

check_style_layer_layout_contains() {
  local style_file="$1"
  local layer_id="$2"
  local key="$3"
  local expected="$4"
  if jq -e --arg id "${layer_id}" --arg key "${key}" --arg expected "${expected}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | (($match.layout[$key] // null) | tostring | contains($expected))
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} layout.${key} contains ${expected}"
  else
    fail "style.json layer=${layer_id} layout.${key} must contain ${expected}"
  fi
}

check_style_layer_filter_contains() {
  local style_file="$1"
  local layer_id="$2"
  local expected="$3"
  if jq -e --arg id "${layer_id}" --arg expected "${expected}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | (($match.filter // null) | tostring | contains($expected))
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} filter contains ${expected}"
  else
    fail "style.json layer=${layer_id} filter must contain ${expected}"
  fi
}

check_style_layer_filter_excludes() {
  local style_file="$1"
  local layer_id="$2"
  local forbidden="$3"
  if jq -e --arg id "${layer_id}" --arg forbidden "${forbidden}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | (($match.filter // null) | tostring | contains($forbidden) | not)
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} filter excludes ${forbidden}"
  else
    fail "style.json layer=${layer_id} filter must not contain ${forbidden}"
  fi
}

check_style_layer_icon_image_contains() {
  local style_file="$1"
  local layer_id="$2"
  local icon_id="$3"
  if jq -e --arg id "${layer_id}" --arg icon "${icon_id}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | ($match.layout["icon-image"] // null) as $icon_image
    | $icon_image != null
      and (($icon_image | tostring) | contains($icon))
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} icon=${icon_id}"
  else
    fail "style.json layer=${layer_id} missing icon=${icon_id}"
  fi
}

check_style_layer_layout_bool() {
  local style_file="$1"
  local layer_id="$2"
  local key="$3"
  local expected="$4"
  if jq -e --arg id "${layer_id}" --arg key "${key}" --argjson expected "${expected}" '
    (.layers | map(select(.id == $id)) | first) as $match
    | $match.layout[$key] == $expected
  ' "${style_file}" >/dev/null; then
    ok "style.json layer=${layer_id} layout.${key}=${expected}"
  else
    fail "style.json layer=${layer_id} layout.${key} must be ${expected}"
  fi
}

verify_style_paint_layers() {
  local style_file="$1"
  [[ -f "${style_file}" ]] || { fail "style.json missing"; return; }
  for layer_id in water island railway; do
    if jq -e --arg id "${layer_id}" '
      (.layers | map(select(.id == $id)) | first) as $match
      | $match != null
        and ($match.type == "line" or $match.type == "fill" or $match.type == "circle" or $match.type == "background")
        and (($match.paint // {}) | type == "object" and (keys | length) > 0)
    ' "${style_file}" >/dev/null 2>&1; then
      ok "style.json paint_layer=${layer_id}"
    else
      fail "style.json missing or empty paint_layer=${layer_id}"
    fi
  done
}

config_dir_export() {
  printf '%s\n' "${CONFIG_DIR}/export-config/$1.json"
}

verify_layer_config_fields() {
  local layer_id="$1"
  shift
  local field
  for field in "$@"; do
    check_export_config_include_tag "${layer_id}" "${field}"
    check_config_final_field_in_include_tags "${layer_id}" "${field}"
    check_config_final_field "${layer_id}" "${field}"
  done
}

verify_layer_metadata_fields() {
  local metadata="$1"
  local layer_id="$2"
  shift 2
  local field
  for field in "$@"; do
    check_metadata_layer_field "${metadata}" "${layer_id}" "${field}"
  done
}

verify_water_config_fields() {
  verify_layer_config_fields water water intermittent place
  check_config_include_tag water natural
  check_export_config_include_tag water natural
}

verify_area_layer_geometry_contracts() {
  local layer expected_tag expected_geometry export_config
  for layer in water building landuse natural_a leisure_a island; do
    case "${layer}" in
      water) expected_tag="natural=water" ;;
      building) expected_tag="building" ;;
      landuse) expected_tag="landuse" ;;
      natural_a) expected_tag="natural" ;;
      leisure_a) expected_tag="leisure" ;;
      island) expected_tag="place" ;;
    esac
    if [[ "${layer}" == "island" ]]; then
      expected_geometry='["Polygon","MultiPolygon","Point"]'
    else
      expected_geometry='["Polygon","MultiPolygon"]'
    fi

    export_config="${CONFIG_DIR}/export-config/${layer}.json"
    require_file "${export_config}"
    if jq -e --arg tag "${expected_tag}" '(.area_tags // []) == [$tag]' "${export_config}" >/dev/null; then
      ok "export-config ${layer} area_tags=${expected_tag}"
    else
      fail "export-config ${layer} area_tags must equal [${expected_tag}]"
    fi
    if jq -e --arg layer "${layer}" --argjson expected "${expected_geometry}" '
      (.source_layers[$layer].post_filter.geometry // []) == $expected
    ' "$(layers_json)" >/dev/null; then
      ok "config ${layer} geometry post_filter"
    else
      fail "config ${layer} post_filter.geometry must equal ${expected_geometry}"
    fi
  done
}

verify_point_label_linear_tag_contracts() {
  local layer expected_linear_tags export_config
  for layer in poi_label highway_point; do
    case "${layer}" in
      poi_label) expected_linear_tags='["amenity","tourism"]' ;;
      highway_point) expected_linear_tags='["highway=services","highway=rest_area"]' ;;
    esac
    export_config="${CONFIG_DIR}/export-config/${layer}.json"
    require_file "${export_config}"
    if jq -e --argjson expected "${expected_linear_tags}" '
      .attributes.type == false
      and .attributes.id == false
      and ((.area_tags // []) | length == 0)
      and (.linear_tags == $expected)
    ' "${export_config}" >/dev/null; then
      ok "export-config ${layer} linear_tags contract"
    else
      fail "export-config ${layer} must disable type/id, omit area_tags, and define linear_tags=${expected_linear_tags}"
    fi
  done
}

verify_water_metadata_fields() {
  local metadata="$1"
  verify_layer_metadata_fields "${metadata}" water water intermittent place
}

verify_waterway_config_fields() {
  verify_layer_config_fields waterway waterway width
}

verify_waterway_metadata_fields() {
  local metadata="$1"
  verify_layer_metadata_fields "${metadata}" waterway waterway width
}

verify_island_config_fields() {
  verify_layer_config_fields island place
}

verify_island_metadata_fields() {
  local metadata="$1"
  verify_layer_metadata_fields "${metadata}" island place
}

verify_island_water_flag() {
  local report json layer count poly_count flagged_in_layer max_area
  report="$(island_water_report_path)"
  if [[ ! -f "${report}" ]]; then
    fail "island in_water report missing: ${report}"
    return
  fi
  json="$(cat "${report}")"
  if ! jq -e '
      .schema_version == 1 and .layer == "island"
      and (.thresholds.sample_points | type == "number")
      and (.thresholds.min_inside_ratio | type == "number")
      and (.thresholds.max_in_water_area_km2 | type == "number")
      and (.inputs.island_polygon_count | type == "number")
      and (.summary.in_water_count | type == "number")
    ' >/dev/null <<< "${json}"; then
    fail "island in_water report schema invalid: ${report}"
    return
  fi
  ok "island in_water report schema"

  if jq -e '.checks.max_in_water_area_within_limit == true' >/dev/null <<< "${json}"; then
    ok "island in_water max area within limit: $(jq -r '.summary.max_in_water_area_km2' <<< "${json}") km2"
  else
    max_area="$(jq -r '[.flagged[].area_km2] | max // 0' <<< "${json}")"
    fail "island in_water max area ${max_area} km2 exceeds $(jq -r '.thresholds.max_in_water_area_km2' <<< "${json}") km2"
  fi

  if [[ "$(sha512_value "$(layers_dir)/water.geojsonseq")" == "$(jq -r '.summary.water_geojsonseq_sha512' <<< "${json}")" ]]; then
    ok "island-water-flag left water layer untouched"
  else
    fail "water layer changed after island-water-flag; report hash mismatch"
  fi

  layer="$(layers_dir)/island.geojsonseq"
  flagged_in_layer="$(tr '\036' '\n' < "${layer}" | sed '/^$/d' | jq -r 'select(.properties.in_water == true) | 1' | wc -l | tr -d ' ')"
  count="$(jq -r '.summary.in_water_count' <<< "${json}")"
  if [[ "${flagged_in_layer}" == "${count}" ]]; then
    ok "island in_water flag count matches report (${count})"
  else
    fail "island in_water flag count mismatch: layer=${flagged_in_layer} report=${count}"
  fi
  poly_count="$(jq -r '.inputs.island_polygon_count' <<< "${json}")"
  if (( poly_count == 0 )); then
    ok "island in_water ratio not applicable: no island polygons"
  elif (( count * 10 <= poly_count )); then
    ok "island in_water ratio within guard (${count}/${poly_count})"
  else
    fail "island in_water ratio out of guard: ${count}/${poly_count}"
  fi
}

verify_island_anchor() {
  local report json layer anchors poly_count
  report="$(island_anchor_report_path)"
  if [[ ! -f "${report}" ]]; then
    fail "island anchor report missing: ${report}"
    return
  fi
  json="$(cat "${report}")"
  if ! jq -e '
      .schema_version == 1 and .layer == "island"
      and (.thresholds.grid_divisions | type == "number")
      and (.summary.polygon_count | type == "number")
      and (.summary.anchor_count | type == "number")
      and (.summary.tier.centroid | type == "number")
      and (.summary.tier.grid | type == "number")
      and (.summary.tier.vertex | type == "number")
    ' >/dev/null <<< "${json}"; then
    fail "island anchor report schema invalid: ${report}"
    return
  fi
  ok "island anchor report schema"

  layer="$(layers_dir)/island.geojsonseq"
  poly_count="$(jq -r '.summary.polygon_count' <<< "${json}")"
  anchors="$(tr '\036' '\n' < "${layer}" | sed '/^$/d' | jq -r 'select(.properties.island_anchor == true) | 1' | wc -l | tr -d ' ')"
  if [[ "${anchors}" == "${poly_count}" \
        && "$(jq -r '.summary.anchor_count' <<< "${json}")" == "${poly_count}" ]]; then
    ok "island anchor count equals polygon count (${anchors})"
  else
    fail "island anchor count mismatch: layer=${anchors} report=$(jq -r '.summary.anchor_count' <<< "${json}") polygons=${poly_count}"
  fi

  if (( poly_count > 0 )); then
    if tr '\036' '\n' < "${layer}" | sed '/^$/d' | jq -e '
        select(.properties.island_anchor == true)
          | (.geometry.type == "Point")
            and (.geometry.coordinates | length == 2)
            and (.properties.island_area_km2 | type == "number")
      ' >/dev/null; then
      ok "island anchors are points with numeric island_area_km2"
    else
      fail "island anchor geometry/field contract violated"
    fi
  fi

  if [[ "$(jq -r '.summary.tier.vertex' <<< "${json}")" == "0" ]]; then
    ok "no island anchor fell back to boundary vertex"
  else
    fail "island anchor boundary-vertex fallback used: $(jq -r '.summary.tier.vertex' <<< "${json}")"
  fi
}

verify_post_filter_rules() {
  local layer_id="$1"
  jq -e --arg layer "${layer_id}" '
    .source_layers[$layer].post_filter.exclude.place
    | index("island") != null and index("islet") != null
  ' "$(layers_json)" >/dev/null \
    && ok "config layer=${layer_id} post_filter excludes place=island and islet" \
    || fail "config layer=${layer_id} post_filter must exclude place=island and islet"
}

TILE_FEATURE_CACHE_DIR="$(mktemp -d)"
trap 'rm -rf "${TILE_FEATURE_CACHE_DIR}"' EXIT

decode_tile_feature_collections() {
  local pmtiles="$1"
  local z="$2" x="$3" y="$4"
  local cache="${TILE_FEATURE_CACHE_DIR}/${z}-${x}-${y}.json"
  if [[ -s "${cache}" ]]; then
    cat "${cache}"
    return
  fi
  pmtiles tile "${pmtiles}" "${z}" "${x}" "${y}" 2>/dev/null \
    | python_with_mvt -c "
import sys, json
try:
    import mapbox_vector_tile
    data = sys.stdin.buffer.read()
    tile = mapbox_vector_tile.decode(data) if data else {}
except Exception:
    tile = {}
print(json.dumps(tile, ensure_ascii=False))
" > "${cache}" 2>/dev/null || printf '{}' > "${cache}"
  cat "${cache}"
}

verify_staged_place_admin_enrichment() {
  local staged report tier_zoom dedupe_tiers admin_display_name
  staged="$(layers_dir)/place_label.geojsonseq"
  report="$(place_admin_report_path)"
  tier_zoom="$(place_label_tier_zoom_json)"
  dedupe_tiers="$(place_label_dedupe_name_tiers_json)"
  admin_display_name="$(place_label_admin_display_name_json)"

  [[ -f "${staged}" ]] || { fail "staged place_label GeoJSONSeq missing"; return; }
  [[ -f "${report}" ]] || { fail "place_label administrative enrichment report missing"; return; }

  if [[ ! -s "${staged}" ]]; then
    if jq -e '
      .schema_version == 1
      and .source.place_feature_count == 0
      and .summary.output_feature_count == 0
      and (.relations | type == "array" and length == 0)
      and (.shared_member_choices | type == "array" and length == 0)
      and (.same_name_tier_duplicates | type == "array" and length == 0)
      and (.redundant_role_members | type == "array" and length == 0)
    ' "${report}" >/dev/null; then
      ok "staged place_label administrative enrichment not applicable: no features"
      ok "place_label administrative enrichment report (zero features)"
    else
      fail "place_label administrative enrichment zero-feature report is invalid"
    fi
    return
  fi

  if jq --seq -n -e '
    [inputs] as $features
    | ($features | length) > 0
      and all($features[];
        (.properties | has("@id") | not)
        and (.properties.label_tier | type == "string" and length > 0)
        and (.properties.label_rank | type == "number"))
      and ([ $features[] | .properties.admin_id? | select(. != null) ] as $admin_ids
           | ($admin_ids | length) == ($admin_ids | unique | length))
      and ([ $features[] | {name: .properties.name, place: .properties.place, coordinates: .geometry.coordinates} ]
           | group_by(.) | all(length == 1))
  ' "${staged}" >/dev/null; then
    ok "staged place_label administrative enrichment"
  else
    fail "staged place_label administrative enrichment is invalid"
  fi

  # 逐要素根级 tippecanoe.minzoom/maxzoom 必须按 label_tier 写入：
  # 否则低 zoom 会丢失市/县，或放大后高等级地名不会逐级让位。
  if jq --seq -n -e --argjson tz "${tier_zoom}" '
    [inputs] as $features
    | ($features | length) > 0
      and all($features[];
        ($tz[.properties.label_tier] // $tz.default) as $z
        | (.tippecanoe.minzoom | type == "number")
          and (.tippecanoe.minzoom == $z.minzoom)
          and ((.tippecanoe.maxzoom // null) == ($z.maxzoom // null)))
  ' "${staged}" >/dev/null; then
    ok "staged place_label per-feature tippecanoe zoom"
  else
    fail "staged place_label per-feature tippecanoe zoom is invalid"
  fi

  # 同名同层去重后不应再出现“无 admin_id 的同名冗余点与带 admin_id 的同名点共存”。
  if jq --seq -n -e --argjson tiers "${dedupe_tiers}" '
    [inputs] as $features
    | ($features | length) > 0
      and ([ $features[]
              | select((.properties.label_tier as $t | ($tiers | index($t)) != null))
              | {name: .properties.name, tier: .properties.label_tier, id: (.properties.admin_id != null)} ]
           | group_by([.name, .tier])
           | all(.[]; ((map(select(.id)) | length) == 0)
                    or ((map(select(.id)) | length) == length)))
  ' "${staged}" >/dev/null; then
    ok "staged place_label same-name-tier dedup"
  else
    fail "staged place_label same-name-tier dedup is invalid"
  fi

  if jq --seq -n -e --argjson adn "${admin_display_name}" '
    [inputs] as $features
    | ($features | length) > 0
      and (if ($adn.enabled // false) then
             all($features[];
               (.properties.official_name // null) as $on
               | (.properties.label_tier // null) as $tier
               | if $on == null then true
                 else ((($adn.tiers // []) | index($tier)) != null
                       or any($adn.locality_keywords[]?; . as $keyword | $on | contains($keyword))) as $eligible
                 | if ($eligible | not) then true else
                   ([ ($adn.target_fields // [])[] as $k | .properties[$k] | select(. != null) ]) as $vals
                   | (([ $vals[] | select(. == $on) ] | length) == 0)
                     or (([ $vals[] | select(. == $on) ] | length) == ($vals | length))
                 end end)
           else true end)
  ' "${staged}" >/dev/null; then
    ok "staged place_label admin display name override"
  else
    fail "staged place_label admin display name override is inconsistent"
  fi

  if jq -e '
    .schema_version == 1
    and (.summary.output_feature_count | type == "number" and . > 0)
    and (.summary.exact_duplicate_dropped_count | type == "number" and . >= 0)
    and (.summary.same_name_tier_dropped_count | type == "number" and . >= 0)
    and (.summary.redundant_role_member_dropped_count | type == "number" and . >= 0)
    and (.summary.admin_display_name_override_count | type == "number" and . >= 0)
    and (.relations | type == "array")
    and (.shared_member_choices | type == "array")
    and (.same_name_tier_duplicates | type == "array")
    and (.redundant_role_members | type == "array")
  ' "${report}" >/dev/null; then
    ok "place_label administrative enrichment report"
  else
    fail "place_label administrative enrichment report is invalid"
  fi
}

verify_staged_area_layer_geometry_types() {
  local layer expected_geometry actual unexpected
  for layer in water building landuse natural_a leisure_a island; do
    if [[ "${layer}" == "island" ]]; then
      expected_geometry='["Polygon","MultiPolygon","Point"]'
    else
      expected_geometry='["Polygon","MultiPolygon"]'
    fi
    actual="$(layers_dir)/${layer}.geojsonseq"
    require_file "${actual}"
    unexpected="$(jq --seq -r --argjson allowed "${expected_geometry}" '
      (.geometry.type // "") as $type
      | select(($allowed | index($type)) == null)
      | if $type == "" then "<missing>" else $type end
    ' "${actual}" | sort -u)"
    if [[ -z "${unexpected}" ]]; then
      ok "staged ${layer} geometry types match post_filter"
    else
      fail "staged ${layer} has disallowed geometry types: $(tr '\n' ',' <<< "${unexpected}" | sed 's/,$//')"
    fi
  done
}

count_layer_features_with_place() {
  local pmtiles="$1" source_layer="$2" z="$3" x="$4" y="$5"
  decode_tile_feature_collections "${pmtiles}" "${z}" "${x}" "${y}" \
    | jq --arg layer "${source_layer}" '
      [((.[$layer].features // [])[])
        | select((.properties.place // "") | IN("island","islet"))]
      | length
    ' 2>/dev/null || printf 0
}

count_waterway_features_with_width() {
  local pmtiles="$1" z="$2" x="$3" y="$4"
  decode_tile_feature_collections "${pmtiles}" "${z}" "${x}" "${y}" \
    | jq '
      {
        total: ([(.waterway.features // [])[]] | length),
        with_width: ([(.waterway.features // [])[] | select((.properties.width != null) and (.properties.width | type == "number"))] | length),
        with_subtype: ([(.waterway.features // [])[] | select((.properties.waterway // "") | length > 0)] | length)
      }
    ' 2>/dev/null || printf '{"total":0,"with_width":0,"with_subtype":0}'
}

verify_waterway_value_distribution() {
  local pmtiles="$1"
  local stats total with_width with_subtype subtype_count width_pct
  stats="$(count_waterway_features_with_width "${pmtiles}" 10 855 397)"
  total="$(jq -r '.total // 0' <<< "${stats}")"
  with_width="$(jq -r '.with_width // 0' <<< "${stats}")"
  with_subtype="$(jq -r '.with_subtype // 0' <<< "${stats}")"
  if (( total == 0 )); then
    log_warn "waterway source-layer has no features at sampled z=10 tile (no value-distribution check)"
    return 0
  fi
  if (( with_width > 0 )); then
    width_pct=$((with_width * 100 / total))
    ok "waterway sampled z=10 tile: ${with_width}/${total} features have numeric width (${width_pct}%)"
    if (( width_pct < 5 )); then
      log_warn "waterway width coverage low (${width_pct}%) at z=10; clients must use waterway subtype as primary"
    fi
  else
    log_warn "waterway sampled z=10 tile: 0/${total} features have numeric width; clients must use waterway subtype as primary"
  fi
  if (( with_subtype > 0 )); then
    ok "waterway sampled z=10 tile: ${with_subtype}/${total} features carry waterway subtype"
  else
    fail "waterway sampled z=10 tile: 0/${total} features carry waterway subtype"
  fi
  subtype_count="$(count_layer_features_with_place_or_subtype "${pmtiles}" waterway 10 855 397)"
  if (( subtype_count > 0 )); then
    ok "waterway source-layer has waterway=river features (sampled z=10 tile)"
  else
    fail "waterway source-layer has no waterway=river features at sampled z=10 tile"
  fi
}

count_layer_features_with_place_or_subtype() {
  local pmtiles="$1" source_layer="$2" z="$3" x="$4" y="$5"
  decode_tile_feature_collections "${pmtiles}" "${z}" "${x}" "${y}" \
    | jq --arg layer "${source_layer}" --arg subtype "river" '
      [((.[$layer].features // [])[])
        | select((.properties.waterway // "") == $subtype)]
      | length
    ' 2>/dev/null || printf 0
}

verify_island_layer_contains_island_polygons() {
  local pmtiles="$1" polygon_count coordinate z x y features
  polygon_count="$(jq -r '.inputs.island_polygon_count // 0' "$(island_water_report_path)" 2>/dev/null || printf 0)"
  if (( polygon_count == 0 )); then
    ok "island source-layer presence not applicable: no island polygons"
    return
  fi
  coordinate="$(jq --seq -n -r '
    first(inputs | select((.properties.place // "") | IN("island", "islet"))
      | [.geometry.coordinates | .. | arrays?
         | select(length == 2 and all(.[]; type == "number"))][0])
    | @tsv
  ' "$(layers_dir)/island.geojsonseq" 2>/dev/null)"
  if [[ -z "${coordinate}" || "${coordinate}" == $'null\tnull' ]]; then
    fail "island source-layer sampling coordinate is unavailable"
    return
  fi
  read -r x y < <(awk -v coordinate="${coordinate}" '
    BEGIN {
      split(coordinate, point, "\t")
      z = 10
      n = 2 ^ z
      pi = atan2(0, -1)
      longitude = point[1]
      latitude = point[2] * pi / 180
      print int((longitude + 180) / 360 * n), int((1 - log(sin(latitude) / cos(latitude) + 1 / cos(latitude)) / pi) / 2 * n)
    }
  ')
  z=10
  features="$(count_layer_features_with_place "${pmtiles}" "island" "${z}" "${x}" "${y}")"
  if [[ "${features}" -gt 0 ]]; then
    ok "island source-layer has place=island/islet features (sampled z=${z} tile)"
  else
    log_warn "island source-layer sample has no place=island/islet features at z=${z}; staging and metadata checks remain authoritative"
  fi
}

verify_water_layer_excludes_island_polygons() {
  local pmtiles="$1"
  local matches
  matches="$(count_layer_features_with_place "${pmtiles}" "water" 10 855 397)"
  if [[ "${matches}" == "0" ]]; then
    ok "water source-layer excludes place=island/islet (sampled z=10 tile)"
  else
    fail "water source-layer contains ${matches} place=island/islet features; post_filter should remove them"
  fi
}

has_file_matching() {
  local dir="$1"
  local pattern="$2"
  [[ -n "$(find "${dir}" -type f -name "${pattern}" -print -quit)" ]]
}

verify_manifest_package_version() {
  local manifest="$1"
  local role="$2"
  local package_version
  package_version="$(jq -r '.huavd_record.package_version // empty' "${manifest}")"
  if [[ -z "${package_version}" ]]; then
    fail "manifest package_version empty (region=${REGION} role=${role})"
  elif [[ ! "${package_version}" =~ ^[A-Za-z0-9._+-]+$ ]]; then
    fail "manifest package_version invalid chars: ${package_version} (region=${REGION} role=${role})"
  else
    ok "manifest package_version (role=${role})"
  fi
}

verify_install_json_package_version() {
  local install_json="$1"
  [[ -f "${install_json}" ]] || return 0
  if jq -e '.offline_maps[]? | (."package-version" // "") | length == 0' "${install_json}" >/dev/null 2>&1; then
    fail "install.json offline_maps package-version missing"
  else
    ok "install.json offline_maps package-version"
  fi
  if jq -e '.bundles[]? | (.["bundle-version"] // "") | length == 0' "${install_json}" >/dev/null 2>&1; then
    fail "install.json bundles bundle-version missing"
  else
    ok "install.json bundles bundle-version"
  fi
}

check_package_assets_for_install_json() {
  local package_dir="$1"
  local install_json="${package_dir}/install.json"
  [[ -f "${install_json}" ]] || return 0

  if jq -e 'any(.offline_maps[]?; ((."glyphs-url" // "") | startswith("huavd-map://glyphs/")))' "${install_json}" >/dev/null; then
    if [[ -d "${package_dir}/glyphs" ]] && has_file_matching "${package_dir}/glyphs" '*.pbf'; then
      ok "package glyph pbf files present"
    else
      fail "package install.json declares glyphs-url but package glyphs/*.pbf is missing"
    fi
  fi

  if jq -e 'any(.offline_maps[]?; ((."styles-url" // "") | startswith("huavd-map://styles/")))' "${install_json}" >/dev/null; then
    if [[ -d "${package_dir}/styles" ]] && has_file_matching "${package_dir}/styles" '*.style.json'; then
      ok "package style json present"
    else
      fail "package install.json declares styles-url but package styles/*.style.json is missing"
    fi
  fi

  style_file="$(find "${package_dir}/styles" -type f -name '*.style.json' -print -quit 2>/dev/null || true)"
  if [[ -n "${style_file}" ]] && jq -e '(.sprite // "") | startswith("huavd-map://sprite/")' "${style_file}" >/dev/null; then
    if [[ -f "${package_dir}/sprite/sprite.json" && -f "${package_dir}/sprite/sprite.png" ]]; then
      ok "package sprite files present"
    else
      fail "package style.json declares sprite but package sprite/sprite.json or sprite/sprite.png is missing"
    fi
  fi
}

verify_packaged_assets() {
  local pack_dir
  pack_dir="$(pack_cache_dir)/${SESSION}"
  if [[ -d "${pack_dir}" ]]; then
    check_package_assets_for_install_json "${pack_dir}"
    verify_install_json_package_version "${pack_dir}/install.json"
  fi
}

verify_role() {
  local role="$1"
  local pmtiles manifest sha_file metadata header_bounds metadata_bounds expected_layers actual_layers actual_sha manifest_sha file_sha manifest_size stat_size build_profile expected_vector expected_vector_layers params
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
  build_profile="$(effective_build_profile "${REGION}" "${role}")"
  params="$(effective_tippecanoe_resolve "${REGION}" "${role}")"
  expected_vector_layers="$(effective_role_layers_json "${REGION}" "${role}")"

  if [[ -n "${build_profile}" ]]; then
    check_eq "pmtiles min_zoom matches profile" "$(pmtiles_min_zoom "${pmtiles}")" "$(jq -r '.min_zoom' <<< "${params}")"
    check_eq "pmtiles max_zoom matches profile" "$(pmtiles_max_zoom "${pmtiles}")" "$(jq -r '.max_zoom' <<< "${params}")"
    if jq -e --arg profile "${build_profile}" --argjson schema "$(tier_profile_schema_version)" '
      .build_profile.name == $profile and .build_profile.schema_version == $schema
    ' "${manifest}" >/dev/null; then
      ok "manifest build profile"
    else
      fail "manifest build profile mismatch"
    fi
  fi
  check_eq "manifest vector_layers" "$(jq -cS '.vector_layers' "${manifest}")" "$(jq -cS . <<< "${expected_vector_layers}")"

  metadata="$(pmtiles_cli_metadata "${pmtiles}")" || fail "pmtiles metadata readable"
  if [[ -n "${metadata}" ]] && jq -e . >/dev/null 2>&1 <<< "${metadata}"; then
    ok "pmtiles metadata JSON"
    expected_vector="$(effective_vector_layers_json "${REGION}" "${role}" "$(pmtiles_max_zoom "${pmtiles}")")"
    expected_layers="$(jq -r 'length' <<< "${expected_vector}")"
    actual_layers="$(jq -r '.vector_layers | length' <<< "${metadata}")"
    check_eq "metadata vector_layers length" "${actual_layers}" "${expected_layers}"
    check_eq "metadata vector_layers" "$(jq -cS '.vector_layers' <<< "${metadata}")" "$(jq -cS . <<< "${expected_vector}")"
    if jq -e 'index("admin_line") != null' <<< "${expected_vector_layers}" >/dev/null; then
      verify_admin_line_metadata_fields "${metadata}"
      verify_staged_admin_line_tiering
    fi
    if [[ -n "${build_profile}" ]]; then
      check_eq "metadata build profile" "$(jq -r '."huavd:build-profile"' <<< "${metadata}")" "${build_profile}"
      check_eq "metadata build profile schema" "$(jq -r '."huavd:build-profile-schema"' <<< "${metadata}")" "$(tier_profile_schema_version)"
    fi
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
      if [[ "${role}" == "base" && -z "${build_profile}" ]]; then
        verify_config_final_fields_declared
        verify_name_locale_config_fields
        verify_label_config_fields
        verify_label_metadata_fields "${metadata}"
        verify_base_fill_config_fields
        verify_base_fill_metadata_fields "${metadata}"
        verify_road_config_fields
        verify_road_metadata_fields "${metadata}"
        verify_railway_config_fields
        verify_railway_metadata_fields "${metadata}"
        verify_water_config_fields
        verify_area_layer_geometry_contracts
        verify_point_label_linear_tag_contracts
        verify_water_metadata_fields "${metadata}"
        verify_waterway_config_fields
        verify_waterway_metadata_fields "${metadata}"
        verify_post_filter_rules "water"
        verify_island_config_fields
        verify_island_metadata_fields "${metadata}"
        verify_island_water_flag
        verify_island_anchor
        verify_staged_place_admin_enrichment
        verify_water_layer_excludes_island_polygons "${pmtiles}"
        verify_island_layer_contains_island_polygons "${pmtiles}"
        verify_waterway_value_distribution "${pmtiles}"
        verify_staged_area_layer_geometry_types
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
      jq -e '.version == 8 and (.sources | type == "object") and (.glyphs | strings | contains("{fontstack}") and contains("{range}.pbf")) and (.sprite | strings | startswith("huavd-map://sprite/"))' "${style_file}" >/dev/null \
        && ok "style.json MapLibre glyph/sprite template" \
        || fail "style.json is missing MapLibre version/source/glyph/sprite template"
      if [[ -n "${build_profile}" ]]; then
        verify_style_source_layers "${style_file}" "${expected_vector_layers}"
      else
        verify_style_text_layers "${style_file}"
        verify_style_paint_layers "${style_file}"
      fi
    fi

    sprite_dir="$(build_sprite_dir)"
    if [[ -d "${sprite_dir}" ]]; then
      if [[ -f "${sprite_dir}/sprite.json" && -f "${sprite_dir}/sprite.png" ]]; then
        ok "sprite json/png present"
      else
        fail "sprite output directory is missing sprite.json or sprite.png"
      fi
      if [[ -f "${sprite_dir}/sprite.json.sha512" && -f "${sprite_dir}/sprite.png.sha512" ]]; then
        ok "sprite sha512 sidecars present"
      else
        fail "sprite output directory is missing sha512 sidecars"
      fi
    fi

    glyphs_dir="$(build_glyphs_dir)"
    if [[ -d "${glyphs_dir}" ]]; then
      if has_file_matching "${glyphs_dir}" '*.pbf'; then
        ok "glyph pbf files present"
      else
        fail "glyph output directory has no pbf files"
      fi
      if has_file_matching "${glyphs_dir}" '*.pbf.sha512'; then
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
    verify_manifest_package_version "${manifest}" "${role}"
    if header_json="$(pmtiles_cli_header_json "${pmtiles}")" && jq -e . >/dev/null 2>&1 <<< "${header_json}"; then
      ok "pmtiles header-json"
      jq -e '
        ((.internal_compression // "gzip") | . == 2 or . == "gzip")
        and ((.tile_compression // "gzip") | . == 2 or . == "gzip")
        and (.tile_type | . == 1 or . == "mvt")
      ' >/dev/null <<< "${header_json}" \
        && ok "pmtiles header-json compression/type" \
        || fail "pmtiles header-json compression/type"
    else
      fail "pmtiles header-json"
    fi
  fi
}

verify_raster_bake_role() {
  local pmtiles manifest sha_file metadata actual_sha file_sha manifest_sha stat_size manifest_size expected_tile_type expected_tile_compression tile_count raster_style raster_style_sha glyphs_dir sprite_dir base_pmtiles bake_plan bake_tiles bake_inputs bake_parameters raster_tile_size
  pmtiles="$(build_pmtiles_path raster_bake)"
  manifest="$(build_manifest_path raster_bake)"
  sha_file="$(build_sha512_path raster_bake)"

  require_file "${pmtiles}"
  require_file "${manifest}"
  require_file "${sha_file}"
  require_cmd pmtiles

  expected_tile_type="$(jq -r '.raster_bake.tile_type' "$(tippecanoe_json)")"
  expected_tile_compression="$(jq -r '.raster_bake.tile_compression' "$(tippecanoe_json)")"
  printf 'verify role=raster_bake file=%s\n' "${pmtiles}"
  check_eq "pmtiles magic" "$(pmtiles_magic "${pmtiles}")" "PMTiles"
  check_eq "pmtiles spec_version" "$(pmtiles_spec_version "${pmtiles}")" "3"
  check_eq "pmtiles internal_compression gzip" "$(pmtiles_internal_compression "${pmtiles}")" "2"
  check_eq "pmtiles tile_type WebP" "$(pmtiles_tile_type "${pmtiles}")" "${expected_tile_type}"
  check_eq "pmtiles tile_compression WebP" "$(pmtiles_tile_compression "${pmtiles}")" "${expected_tile_compression}"

  tile_count="$(pmtiles_addressed_tiles_count "${pmtiles}")"
  if (( tile_count > 0 )); then
    ok "raster_bake addressed tile count"
  else
    fail "raster_bake addressed tile count must be positive"
  fi

  stat_size="$(stat -c %s "${pmtiles}")"
  manifest_size="$(jq -r '.output.size_bytes' "${manifest}")"
  check_eq "manifest output.size_bytes" "${manifest_size}" "${stat_size}"
  check_eq "manifest vector_layers" "$(jq -cS '.vector_layers' "${manifest}")" '[]'
  check_eq "manifest raster_bake.encoding" "$(jq -r '.raster_bake.encoding' "${manifest}")" "webp"
  check_eq "manifest raster_bake.tile_count" "$(jq -r '.raster_bake.tile_count' "${manifest}")" "${tile_count}"
  check_eq "manifest raster_bake.tile_type" "$(jq -r '.raster_bake.tile_type' "${manifest}")" "${expected_tile_type}"
  check_eq "manifest raster_bake.tile_compression" "$(jq -r '.raster_bake.tile_compression' "${manifest}")" "${expected_tile_compression}"
  base_pmtiles="$(build_pmtiles_path base)"
  require_file "${base_pmtiles}"
  check_eq "manifest raster_bake base file" "$(jq -r '.raster_bake.base_input.file' "${manifest}")" "$(basename -- "${base_pmtiles}")"
  check_eq "manifest raster_bake base sha512" "$(jq -r '.raster_bake.base_input.sha512' "${manifest}")" "$(sha512_value "${base_pmtiles}")"
  check_eq "manifest raster_bake base bounds" "$(jq -c '.raster_bake.base_input.bounds' "${manifest}")" "$(pmtiles_bounds "${base_pmtiles}" | jq -c .)"

  bake_plan="$(bake_cache_dir)/plan.json"
  bake_tiles="$(bake_cache_dir)/tiles.tsv"
  bake_inputs="$(bake_cache_dir)/inputs.sha512"
  bake_parameters="$(bake_cache_dir)/parameters.json"
  require_file "${bake_plan}"
  require_file "${bake_tiles}"
  require_file "${bake_inputs}"
  require_file "${bake_parameters}"
  raster_tile_size="$(jq -r '.effective.tile_size // empty' "${bake_parameters}")"
  [[ "${raster_tile_size}" =~ ^[1-9][0-9]*$ ]] || fail "raster_bake parameters tile_size"
  check_eq "manifest raster_bake plan sha512" "$(jq -r '.raster_bake.plan.plan_sha512' "${manifest}")" "$(sha512_value "${bake_plan}")"
  check_eq "manifest raster_bake tiles sha512" "$(jq -r '.raster_bake.plan.tiles_sha512' "${manifest}")" "$(sha512_value "${bake_tiles}")"
  check_eq "manifest raster_bake input fingerprint" "$(jq -r '.raster_bake.plan.input_fingerprint' "${manifest}")" "$(<"${bake_inputs}")"
  check_eq "manifest raster_bake requested tile count" "$(jq -r '.raster_bake.plan.requested_tile_count' "${manifest}")" "${tile_count}"
  check_eq "manifest raster_bake tile size" "$(jq -r '.raster_bake.tile_size' "${manifest}")" "${raster_tile_size}"
  if jq -e '
    (.raster_bake.plan.tiles_by_zoom | type == "array" and length > 0)
    and ((.raster_bake.plan.tiles_by_zoom | map(.tile_count) | add) == .raster_bake.plan.requested_tile_count)
  ' "${manifest}" >/dev/null; then
    ok "manifest raster_bake plan coverage"
  else
    fail "manifest raster_bake plan coverage"
  fi

  metadata="$(pmtiles_cli_metadata "${pmtiles}")" || fail "pmtiles metadata readable"
  if [[ -n "${metadata}" ]] && jq -e . >/dev/null 2>&1 <<< "${metadata}"; then
    ok "pmtiles metadata JSON"
    check_eq "metadata format" "$(jq -r '.format' <<< "${metadata}")" "webp"
    check_eq "metadata vector_layers" "$(jq -cS '.vector_layers' <<< "${metadata}")" '[]'
    check_eq "metadata huavd:asset-role" "$(jq -r '."huavd:asset-role"' <<< "${metadata}")" "raster-baked"
    check_eq "metadata huavd:raster-encoding" "$(jq -r '."huavd:raster-encoding"' <<< "${metadata}")" "webp"
    check_eq "metadata huavd:tile-count" "$(jq -r '."huavd:tile-count"' <<< "${metadata}")" "${tile_count}"
  else
    fail "pmtiles metadata JSON"
  fi
  check_eq "metadata huavd:raster-tile-size" "$(jq -r '."huavd:raster-tile-size" // empty' <<< "${metadata}")" "${raster_tile_size}"

  actual_sha="$(sha512_value "${pmtiles}")"
  file_sha="$(awk '{print $1; exit}' "${sha_file}")"
  manifest_sha="$(jq -r '.output.sha512' "${manifest}")"
  check_eq "sha512 sidecar" "${file_sha}" "${actual_sha}"
  check_eq "manifest output.sha512" "${manifest_sha}" "${actual_sha}"

  raster_style="$(build_raster_style_path)"
  if [[ -f "${raster_style}" ]]; then
    jq -e '
      .version == 8
      and any(.sources[]; .type == "raster")
      and any(.layers[]; .type == "raster")
    ' "${raster_style}" >/dev/null \
      && ok "raster style source/layer" \
      || fail "raster style must declare a raster source and layer"
  else
    fail "raster style missing: ${raster_style}"
  fi

  raster_style_sha="${raster_style}.sha512"
  if [[ -f "${raster_style_sha}" ]]; then
    check_eq "raster style sha512 sidecar" "$(awk '{print $1; exit}' "${raster_style_sha}")" "$(sha512_value "${raster_style}")"
  else
    fail "raster style sha512 sidecar missing: ${raster_style_sha}"
  fi

  glyphs_dir="$(build_glyphs_dir)"
  sprite_dir="$(build_sprite_dir)"
  if [[ -d "${glyphs_dir}" ]] && [[ -n "$(find -L "${glyphs_dir}" -type f -name '*.pbf' -print -quit)" ]]; then
    ok "raster glyphs present"
  else
    fail "raster glyphs missing: ${glyphs_dir}"
  fi
  if [[ -f "${sprite_dir}/sprite.json" && -f "${sprite_dir}/sprite.png" ]]; then
    ok "raster sprite present"
  else
    fail "raster sprite missing: ${sprite_dir}"
  fi

  verify_raster_bake_webp_samples "${pmtiles}" "${bake_plan}"

  if ((STRICT)); then
    verify_manifest_package_version "${manifest}" raster_bake
  fi
}

verify_raster_bake_webp_samples() {
  local pmtiles="$1" plan="$2" sample_dir z x y tile_file expected_size=256 samples=0
  require_cmd dwebp python3
  sample_dir="$(mktemp -d)"
  while IFS=$'\t' read -r z x y; do
    [[ -n "${z}" ]] || continue
    tile_file="${sample_dir}/${z}-${x}-${y}.webp"
    if pmtiles tile "${pmtiles}" "${z}" "${x}" "${y}" > "${tile_file}" 2>/dev/null \
      && validate_raster_bake_webp_file "${tile_file}" "${expected_size}"; then
      ok "raster_bake decoded WebP sample z=${z} x=${x} y=${y}"
    else
      fail "raster_bake decoded WebP sample z=${z} x=${x} y=${y}"
    fi
    samples=$((samples + 1))
  done < <(jq -r '
    (.tiles_by_zoom | length) as $zoom_count
    | [.tiles_by_zoom[0], .tiles_by_zoom[($zoom_count / 2 | floor)], .tiles_by_zoom[-1]]
    | unique_by(.zoom)
    | .[]
    | [.zoom, (((.x_range[0] + .x_range[1]) / 2) | floor), (((.y_range[0] + .y_range[1]) / 2) | floor)]
    | @tsv
  ' "${plan}")
  rm -rf "${sample_dir}"
  (( samples > 0 )) || fail "raster_bake decoded WebP samples unavailable"
}

validate_raster_bake_webp_file() {
  local file="$1" expected_size="$2"
  dwebp "${file}" -o /dev/null >/dev/null 2>&1 || return 1
  python3 - "${file}" "${expected_size}" <<'PY'
import struct
import sys

path, expected_size = sys.argv[1], int(sys.argv[2])
data = open(path, "rb").read()
if len(data) < 16 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
    raise SystemExit(1)
offset = 12
while offset + 8 <= len(data):
    kind = data[offset:offset + 4]
    length = struct.unpack_from("<I", data, offset + 4)[0]
    payload = data[offset + 8:offset + 8 + length]
    if len(payload) != length:
        raise SystemExit(1)
    if kind == b"VP8 " and len(payload) >= 10 and payload[3:6] == b"\x9d\x01\x2a":
        width = struct.unpack_from("<H", payload, 6)[0] & 0x3fff
        height = struct.unpack_from("<H", payload, 8)[0] & 0x3fff
        break
    if kind == b"VP8L" and len(payload) >= 5 and payload[0] == 0x2f:
        bits = struct.unpack_from("<I", payload, 1)[0]
        width = (bits & 0x3fff) + 1
        height = ((bits >> 14) & 0x3fff) + 1
        break
    if kind == b"VP8X" and len(payload) >= 10:
        width = int.from_bytes(payload[4:7], "little") + 1
        height = int.from_bytes(payload[7:10], "little") + 1
        break
    offset += 8 + length + (length & 1)
else:
    raise SystemExit(1)
if width != expected_size or height != expected_size:
    raise SystemExit(1)
PY
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
    verify_manifest_package_version "${manifest}" "dem"
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

if ((STRICT)); then
  verify_export_config_include_tags
fi

verified_any=0
while IFS= read -r role; do
  if [[ "${ROLE}" == "both" && ! -f "$(build_pmtiles_path "${role}")" && "${role}" == "building" ]]; then
    log_warn "skip missing optional building role"
    continue
  fi
  if [[ "${role}" == "dem" ]]; then
    verify_dem_role
  elif [[ "${role}" == "raster_bake" ]]; then
    verify_raster_bake_role
  else
    verify_role "${role}"
  fi
  verified_any=1
done < <(role_list "${ROLE}")

(( verified_any == 1 )) || die "${HUAVD_EXIT_INPUT}" "no artifacts found to verify for role=${ROLE}"

if ((STRICT)); then
  verify_packaged_assets
fi

mapfile -t cross_regions < <(
  find "${WORKDIR}/outputs" -maxdepth 1 -type f -name '*.base.pmtiles' 2>/dev/null \
    | sed -E 's|.*/||; s|-[0-9]{8}\.base\.pmtiles$||' \
    | sort -u
)
if (( ${#cross_regions[@]} >= 2 )); then
  log_info "running cross-region linters across ${#cross_regions[@]} regions"
  "${SCRIPT_DIR}/style-lint.sh" || ((FAILURES++))
  "${SCRIPT_DIR}/viewport-lint.sh" || ((FAILURES++))
else
  log_info "skipping cross-region linters: only ${#cross_regions[@]} region present"
fi

if ((FAILURES == 0)); then
  printf 'verify: PASS\n'
else
  printf 'verify: FAIL (%d)\n' "${FAILURES}"
  exit "${HUAVD_EXIT_VERIFY}"
fi
