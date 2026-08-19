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
  if [[ ! -s "${target}" || "${source}" -nt "${target}" ]]; then
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

styles_json() {
  config_json_path styles
}

dem_json() {
  config_json_path dem
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
  local current="${region}"
  local source_id mapped parent

  while [[ -n "${current}" && "${current}" != "null" ]]; do
    source_id="$(region_get huavd.source_id "${current}")"
    if [[ -n "${source_id}" && "${source_id}" != "null" ]]; then
      printf '%s\n' "${source_id}"
      return 0
    fi

    mapped="$(jq -r --arg id "${current}" '.source_id_mappings[$id] // empty' "$(regions_json)")"
    if [[ -n "${mapped}" && "${mapped}" != "null" ]]; then
      printf '%s\n' "${mapped}"
      return 0
    fi

    parent="$(region_get geofabrik.parent_region "${current}")"
    current="${parent}"
  done
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

region_name_locale_priority_json() {
  local region="$1"
  local override
  override="$(region_json "${region}" | jq -c '.huavd.name_locale_priority // []')"
  if jq -e 'type == "array" and length > 0' >/dev/null <<< "${override}"; then
    printf '%s\n' "${override}"
  else
    jq -c '.global.name_coalesce_order' "$(layers_json)"
  fi
}

available_locales_json() {
  jq -c '[.locales[].tag] | reduce .[] as $tag ([]; if index($tag) then . else . + [$tag] end)' "$(glyphs_json)"
}

style_locales_json() {
  jq -c '[.locales[].tag] | reduce .[] as $tag ([]; if index($tag) then . else . + [$tag] end)' "$(styles_json)"
}

glyphs_url_template() {
  jq -r '.generator.url_template // "huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf"' "$(glyphs_json)"
}

styles_url() {
  printf 'huavd-map://styles/%s\n' "$(basename -- "$(build_style_path)")"
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
  validate_yyyymmdd "${YYYYMMDD}"

  # 运行期环境变量覆盖（per-role > 全局）。命中后跳过模板渲染并 log 来源。
  local env_role="${role^^}"
  local env_var_name="HUAVD_MAP_PACKAGE_VERSION_${env_role}"
  local env_value="${!env_var_name-${HUAVD_MAP_PACKAGE_VERSION:-}}"
  local env_source=""
  if [[ -n "${env_value}" ]]; then
    env_source="${env_var_name}"
  elif [[ -n "${HUAVD_MAP_PACKAGE_VERSION:-}" ]]; then
    env_value="${HUAVD_MAP_PACKAGE_VERSION}"
    env_source="HUAVD_MAP_PACKAGE_VERSION"
  fi

  local template=""
  if [[ -z "${env_value}" ]]; then
    # 父子继承模板，沿 geofabrik.parent_region 上溯
    template="$(region_get_inherited huavd.package_version_template "${region}" || true)"
    if [[ -z "${template}" || "${template}" == "null" ]]; then
      # per-role 默认模板优先，否则使用全局默认
      local role_template
      role_template="$(jq -r --arg r "${role}" '.huavd.package_version_template_per_role[$r] // empty' "$(regions_json)")"
      if [[ -n "${role_template}" && "${role_template}" != "null" ]]; then
        template="${role_template}"
      else
        template="$(jq -r '.huavd.default_package_version_template // "{yyyymmdd}.{role}"' "$(regions_json)")"
      fi
    fi
  else
    if [[ ! "${env_value}" =~ ^[A-Za-z0-9._+-]+$ ]]; then
      die "${HUAVD_EXIT_INPUT}" "${env_source} contains invalid chars: ${env_value}"
    fi
    log_info "package_version source=env (${env_source}=${env_value})"
    template="${env_value}"
  fi

  # 历史契约：building/dem 时把模板中第一个 .{yyyymmdd} 替换为 -<role>.{yyyymmdd}，
  # 兼容 region 自带模板（如 v1.0.{yyyymmdd}.base 在 building 下变 v1.0-building.20260818.base）。
  # 占位符提取到变量是为了避免 bash 大括号匹配把 .{yyyymmdd} 的 } 当作 ${...} 闭合符。
  local yyyymmdd_placeholder="{yyyymmdd}"
  local role_placeholder="{role}"
  local yyyymmdd_with_dot=".${yyyymmdd_placeholder}"
  if [[ "${role}" == "building" ]]; then
    template="${template/${yyyymmdd_with_dot}/-building.${yyyymmdd_placeholder}}"
  elif [[ "${role}" == "dem" ]]; then
    template="${template/${yyyymmdd_with_dot}/-dem.${yyyymmdd_placeholder}}"
  fi

  template="${template//${yyyymmdd_placeholder}/${YYYYMMDD}}"
  template="${template//${role_placeholder}/${role}}"

  printf '%s\n' "${template}"
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
  elif [[ "${role}" == "dem" ]]; then
    printf 'dem-raster\n'
  else
    printf 'base-vector\n'
  fi
}

role_source_type() {
  local role="${1:-base}"
  if [[ "${role}" == "dem" ]]; then
    printf 'dem\n'
  else
    printf 'osm-pbf\n'
  fi
}

dem_default_source_id() {
  jq -r '.dem.default_source // empty' "$(dem_json)"
}

dem_default_encoding() {
  jq -r '.dem.default_encoding // empty' "$(dem_json)"
}

dem_source_json() {
  local source_id="$1"
  jq -e --arg id "${source_id}" '.dem.sources[] | select(.id == $id)' "$(dem_json)"
}

dem_source_value() {
  local source_id="$1"
  local key="$2"
  dem_source_json "${source_id}" | jq -r --arg key "${key}" 'getpath($key | split(".")) // empty'
}

dem_region_required() {
  local region="$1"
  local value
  value="$(region_get huavd.dem_required "${region}")"
  [[ "${value}" == "true" ]]
}

dem_region_source_id() {
  local region="$1"
  local source_id
  source_id="$(region_get_inherited huavd.dem_source_id "${region}" || true)"
  if [[ -n "${source_id}" && "${source_id}" != "null" ]]; then
    printf '%s\n' "${source_id}"
  else
    dem_default_source_id
  fi
}

dem_allowed_encoding() {
  local encoding="$1"
  jq -e --arg encoding "${encoding}" '(.dem.allowed_encodings // []) | index($encoding)' "$(dem_json)" >/dev/null
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
    building) printf '12\n' ;;
    natural_line) printf '10\n' ;;
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
    road|building|natural_line|poi_label|transport_label) printf '15\n' ;;
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
