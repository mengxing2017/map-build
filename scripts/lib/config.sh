#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_COMMON_LOADED:-}" ]]; then
  # shellcheck source=common.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
fi
HUAVD_MAP_BUILD_CONFIG_LOADED=1

yaml_to_json() {
  local source="$1"
  local target="$2"
  ensure_dir "$(dirname -- "${target}")"

  if command -v yq >/dev/null 2>&1; then
    if yq -o=json '.' "${source}" > "${target}" 2>/dev/null; then
      return
    fi
    if yq '.' "${source}" > "${target}" 2>/dev/null; then
      return
    fi
  fi

  if command -v python3 >/dev/null 2>&1; then
    if python3 - "${source}" > "${target}" <<'PY' 2>/dev/null; then
import json
import sys
import yaml

with open(sys.argv[1], "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)
json.dump(data, sys.stdout, ensure_ascii=False, indent=2)
sys.stdout.write("\n")
PY
      return
    fi
  fi

  if command -v ruby >/dev/null 2>&1; then
    if ruby -ryaml -rjson -e 'puts JSON.pretty_generate(YAML.load_file(ARGV.fetch(0)))' "${source}" > "${target}" 2>/dev/null; then
      return
    fi
  fi

  die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "no YAML parser available; install yq or python3+PyYAML"
}

config_json_path() {
  local name="$1"
  local source="${CONFIG_DIR}/${name}.yaml"
  local target="$(configs_cache_dir)/${name}.json"
  require_file "${source}"
  if [[ ! -f "${target}" || "${source}" -nt "${target}" ]]; then
    yaml_to_json "${source}" "${target}"
  fi
  printf '%s\n' "${target}"
}

regions_json() {
  config_json_path regions
}

layers_json() {
  config_json_path layers
}

tippecanoe_json() {
  config_json_path tippecanoe
}

glyphs_json() {
  config_json_path glyphs
}

region_json() {
  local region="$1"
  jq -e --arg id "${region}" '.regions[] | select(.id == $id)' "$(regions_json)"
}

region_exists() {
  local region="$1"
  jq -e --arg id "${region}" 'any(.regions[]; .id == $id)' "$(regions_json)" >/dev/null
}

require_region() {
  local region="$1"
  region_exists "${region}" || die "${HUAVD_EXIT_INPUT}" "region is not configured: ${region}"
}

region_get() {
  local key="$1"
  local region="$2"
  region_json "${region}" | jq -r --arg key "${key}" 'getpath($key | split(".")) // empty'
}

region_get_inherited() {
  local key="$1"
  local region="$2"
  local current="${region}"
  local value parent

  while [[ -n "${current}" && "${current}" != "null" ]]; do
    value="$(region_get "${key}" "${current}")"
    if [[ -n "${value}" && "${value}" != "null" ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
    parent="$(region_get geofabrik.parent_region "${current}")"
    current="${parent}"
  done

  return 1
}

region_slug_configured() {
  local region="$1"
  local configured
  configured="$(region_get slug "${region}")"
  if [[ -n "${configured}" ]]; then
    printf '%s\n' "${configured}"
  else
    slugify_region "${region}"
  fi
}

region_id_from_slug() {
  local slug="$1"
  jq -r --arg slug "${slug}" '.regions[] | select(.slug == $slug) | .id' "$(regions_json)" | head -n 1
}

region_source_id() {
  local region="$1"
  local source_id
  source_id="$(region_get huavd.source_id "${region}")"
  if [[ -n "${source_id}" && "${source_id}" != "null" ]]; then
    printf '%s\n' "${source_id}"
    return
  fi
  jq -r --arg id "${region}" '.source_id_mappings[$id] // empty' "$(regions_json)"
}

region_stable_id() {
  local region="$1"
  region_get huavd.region_id "${region}"
}

region_style_id() {
  local region="$1"
  local style_id
  style_id="$(region_get_inherited huavd.style_id "${region}" || true)"
  printf '%s\n' "${style_id:-osm-dev}"
}

available_locales_json() {
  jq -c '[.locales[].tag] | reduce .[] as $tag ([]; if index($tag) then . else . + [$tag] end)' "$(glyphs_json)"
}

glyphs_url_template() {
  jq -r '.generator.url_template // "huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf"' "$(glyphs_json)"
}

region_asset_role() {
  local region="$1"
  region_get_inherited huavd.asset_role "${region}"
}

region_source_type() {
  local region="$1"
  region_get_inherited huavd.source_type "${region}"
}

region_package_version() {
  local region="$1"
  local role="${2:-base}"
  local template
  template="$(region_get huavd.package_version_template "${region}")"
  if [[ -z "${template}" || "${template}" == "null" ]]; then
    printf '\n'
    return
  fi
  if [[ "${role}" == "building" ]]; then
    template="${template/.{yyyymm}/-building.{yyyymm}}"
  fi
  printf '%s\n' "${template//\{yyyymm\}/${YYYYMM}}"
}

role_source_id() {
  local region="${1:-}"
  local role="${2:-base}"
  : "${role}"
  region_source_id "${region}"
}

role_asset_role() {
  local role="${1:-base}"
  if [[ "${role}" == "building" ]]; then
    printf 'building-vector\n'
  else
    printf 'base-vector\n'
  fi
}

role_source_type() {
  local role="${1:-base}"
  : "${role}"
  printf 'osm-pbf\n'
}

building_role_enabled() {
  local region="$1"
  [[ "$(region_asset_role "${region}")" == "building-vector" && "$(region_source_type "${region}")" == "derived-building" ]]
}

region_basename() {
  local region="$1"
  printf '%s\n' "${region##*/}"
}

region_pbf_url() {
  local region="$1"
  region_get geofabrik.pbf_url "${region}"
}

region_md5_url() {
  local region="$1"
  region_get geofabrik.md5_url "${region}"
}

region_pbf_basename() {
  local region="$1"
  region_get geofabrik.basename "${region}"
}

layers_list() {
  jq -r '.source_layers | to_entries | sort_by(.value.order) | .[].key' "$(layers_json)"
}

layer_exists() {
  local layer="$1"
  jq -e --arg layer "${layer}" '.source_layers[$layer] != null' "$(layers_json)" >/dev/null
}

selected_layers() {
  local layers="${1:-}"
  if [[ -z "${layers}" || "${layers}" == "all" ]]; then
    layers_list
    return
  fi
  tr ',' '\n' <<< "${layers}" | while IFS= read -r layer; do
    [[ -n "${layer}" ]] || continue
    layer_exists "${layer}" || die "${HUAVD_EXIT_INPUT}" "unknown layer: ${layer}"
    printf '%s\n' "${layer}"
  done
}

load_selected_layers() {
  local output_var="$1"
  local layers="$2"
  local tmp
  tmp="$(mktemp)"
  if selected_layers "${layers}" > "${tmp}"; then
    local -n selected_ref="${output_var}"
    mapfile -t selected_ref < "${tmp}"
    rm -f "${tmp}"
  else
    local code="$?"
    rm -f "${tmp}"
    exit "${code}"
  fi
}

role_layers_json() {
  local role="${1:-base}"
  if [[ "${role}" == "building" ]]; then
    jq -n '["building"]'
  else
    jq -c '.defaults.source_layers' "$(tippecanoe_json)"
  fi
}

role_layers() {
  local role="${1:-base}"
  role_layers_json "${role}" | jq -r '.[]'
}

layer_tags_filter_args() {
  local layer="$1"
  jq -r --arg layer "${layer}" '.source_layers[$layer].tags_filter[]' "$(layers_json)"
}

layer_include_tags() {
  local layer="$1"
  jq -r --arg layer "${layer}" '.source_layers[$layer].include_tags[]' "$(layers_json)"
}

layer_final_fields_json() {
  local layer="$1"
  jq -c --arg layer "${layer}" '.source_layers[$layer].final_fields // {}' "$(layers_json)"
}

layer_final_field_names_json() {
  local layer="$1"
  layer_final_fields_json "${layer}" | jq -c 'keys'
}

layer_min_zoom() {
  local layer="$1"
  case "${layer}" in
    building) printf '13\n' ;;
    leisure_a) printf '10\n' ;;
    place_label) printf '2\n' ;;
    poi_label) printf '14\n' ;;
    transport_label) printf '13\n' ;;
    *) printf '0\n' ;;
  esac
}

layer_default_max_zoom() {
  local layer="$1"
  case "${layer}" in
    road|building|poi_label|transport_label) printf '15\n' ;;
    admin) printf '8\n' ;;
    *) printf '14\n' ;;
  esac
}

layer_effective_max_zoom() {
  local layer="$1"
  local role="$2"
  local tile_max="$3"
  if [[ "${role}" == "building" && "${layer}" == "building" ]]; then
    printf '%s\n' "${tile_max}"
    return
  fi
  local default_max
  default_max="$(layer_default_max_zoom "${layer}")"
  if (( default_max > tile_max )); then
    printf '%s\n' "${tile_max}"
  else
    printf '%s\n' "${default_max}"
  fi
}

vector_layers_json() {
  local role="${1:-base}"
  local tile_max="${2:-15}"
  local tmp
  tmp="$(mktemp)"
  while IFS= read -r layer; do
    jq -n \
      --arg id "${layer}" \
      --argjson minzoom "$(layer_min_zoom "${layer}")" \
      --argjson maxzoom "$(layer_effective_max_zoom "${layer}" "${role}" "${tile_max}")" \
      --argjson fields "$(layer_final_fields_json "${layer}")" \
      '{id:$id,minzoom:$minzoom,maxzoom:$maxzoom,fields:$fields}' >> "${tmp}"
  done < <(role_layers "${role}")
  jq -s '.' "${tmp}"
  rm -f "${tmp}"
}

tippecanoe_resolve() {
  local region="$1"
  local role="${2:-base}"
  local tip_json
  tip_json="$(tippecanoe_json)"
  local resolved
  resolved="$(jq -c '.defaults' "${tip_json}")"

  if [[ "${role}" == "building" ]]; then
    resolved="$(jq -c '. as $root | $root.defaults + {
      min_zoom: $root.building_vector.min_zoom,
      max_zoom: $root.building_vector.max_zoom,
      maximum_tile_bytes: $root.building_vector.maximum_tile_bytes,
      output_role: $root.building_vector.output_role,
      source_layers: $root.building_vector.source_layers
    }' "${tip_json}")"
  fi

  while IFS= read -r override; do
    local pattern
    pattern="$(jq -r '.region_match' <<< "${override}")"
    local shell_pattern="${pattern//\*\*/\*}"
    if [[ "${region}" == ${shell_pattern} ]]; then
      local clean_override
      clean_override="$(jq -c 'del(.region_match, .building_height_derivation)' <<< "${override}")"
      resolved="$(jq -c -s '.[0] + .[1]' <(printf '%s\n' "${resolved}") <(printf '%s\n' "${clean_override}"))"
    fi
  done < <(jq -c '.high_density[]?' "${tip_json}")

  printf '%s\n' "${resolved}" | jq -c '.'
}
