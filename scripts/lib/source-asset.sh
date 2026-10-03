#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_CONFIG_LOADED:-}" ]]; then
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
fi

source_asset_json() {
  jq -e --arg id "$1" '.assets[] | select(.id == $id)' "$(source_assets_json)"
}

require_source_asset() {
  [[ "$1" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "${HUAVD_EXIT_INPUT}" "invalid source asset id: $1"
  source_asset_json "$1" >/dev/null || die "${HUAVD_EXIT_INPUT}" "source asset is not configured: $1"
}

source_asset_input_regions() {
  local asset="$1" config mode root
  config="$(source_asset_json "${asset}")"
  mode="$(jq -r '.inputs.mode' <<< "${config}")"
  root="$(jq -r '.inputs.root_region // empty' <<< "${config}")"
  case "${mode}" in
    direct-children)
      jq -r --arg root "${root}" '.regions[] | select(.geofabrik.parent_region == $root) | .id' "$(regions_json)"
      ;;
    explicit)
      jq -r '.inputs.regions[]' <<< "${config}"
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unsupported source asset inputs.mode: ${mode}" ;;
  esac
}

source_asset_input_path() {
  local asset="$1" region="$2" path
  path="$(source_asset_json "${asset}" | jq -r --arg region "${region}" '.inputs.path_overrides[$region] // .inputs.path_template // empty')"
  [[ -n "${path}" ]] || die "${HUAVD_EXIT_INPUT}" "source asset ${asset} has no input path for region: ${region}"
  path="${path//\{region-basename\}/$(region_basename "${region}")}"
  resolve_workspace_path "${path}"
}

source_asset_adapter() { source_asset_json "$1" | jq -r '.adapter'; }
source_asset_license_ref() { source_asset_json "$1" | jq -r '.license_ref'; }
source_asset_layer_profile() { source_asset_json "$1" | jq -r '.layer_profile'; }
source_asset_coverage_region() { source_asset_json "$1" | jq -r '.coverage.region'; }

source_asset_validate() {
  local asset="$1" config adapter region
  require_source_asset "${asset}"
  config="$(source_asset_json "${asset}")"
  jq -e --arg id "${asset}" '
    .schema_version == 1
    and ([.assets[].id] | length == (unique | length))
    and (.assets[] | select(.id == $id)
      | .provider == "osm-pbf-set"
      and (.version | type == "string" and length > 0)
      and (.coverage.region | type == "string" and length > 0)
      and (.license_ref | type == "string" and length > 0)
      and (.adapter | type == "string" and length > 0)
      and .layer_profile == "base-v1"
      and (.inputs.mode | IN("direct-children", "explicit"))
      and ((.inputs.path_template // null) | type == "null" or (type == "string" and length > 0))
      and ((.inputs.path_overrides // {}) | type == "object" and all(.[]; type == "string" and length > 0))
      and (.inputs.md5_sidecar == true)
      and ((.inputs.regions // []) | type == "array" and all(.[]; type == "string")))
  ' "$(source_assets_json)" >/dev/null || die "${HUAVD_EXIT_INPUT}" "invalid source asset configuration: ${asset}"
  region="$(source_asset_coverage_region "${asset}")"
  require_region "${region}"
  adapter="$(source_asset_adapter "${asset}")"
  jq -e --arg id "${adapter}" '.adapters[] | select(.id == $id and .provider == "osm-pbf-set")' "$(adapters_json)" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "source asset ${asset} references unsupported adapter: ${adapter}"
  while IFS= read -r region; do
    require_region "${region}"
    [[ "$(source_asset_input_path "${asset}" "${region}")" == *.osm.pbf ]] \
      || die "${HUAVD_EXIT_INPUT}" "source asset input must be an .osm.pbf file: ${asset}/${region}"
  done < <(source_asset_input_regions "${asset}")
}

source_asset_fingerprint() {
  local asset="$1" region input
  {
    source_asset_json "${asset}" | jq -cS .
    while IFS= read -r region; do
      input="$(source_asset_input_path "${asset}" "${region}")"
      printf '%s %s\n' "$(sha512_value "${input}")" "${region}"
    done < <(source_asset_input_regions "${asset}")
  } | sha512_stdin
}

source_asset_cache_dir() {
  printf '%s/cache/adapters/%s/%s\n' "${WORKDIR}" "$1" "$(source_asset_fingerprint "$1")"
}
