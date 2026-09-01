#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_CONFIG_LOADED:-}" ]]; then
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
fi

composite_json() {
  local id="$1"
  jq -e --arg id "${id}" '.composites[] | select(.id == $id)' "$(composites_json)"
}

require_composite() {
  local id="$1"
  [[ "${id}" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid composite id: ${id}"
  composite_json "${id}" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "composite is not configured: ${id}"
}

composite_target_region() {
  composite_json "$1" | jq -r '.target_region'
}

region_has_ancestor() {
  local region="$1" ancestor="$2" current parent
  current="$(region_get geofabrik.parent_region "${region}")"
  while [[ -n "${current}" && "${current}" != "null" ]]; do
    [[ "${current}" == "${ancestor}" ]] && return 0
    parent="$(region_get geofabrik.parent_region "${current}")"
    current="${parent}"
  done
  return 1
}

composite_base_source_regions() {
  local id="$1" config mode root
  config="$(composite_json "${id}")"
  mode="$(jq -r '.sources.mode' <<< "${config}")"
  root="$(jq -r '.sources.root_region' <<< "${config}")"
  case "${mode}" in
    direct-children)
      jq -r --arg root "${root}" '.regions[] | select(.geofabrik.parent_region == $root) | .id' "$(regions_json)"
      ;;
    descendants)
      while IFS= read -r region; do
        region_has_ancestor "${region}" "${root}" && printf '%s\n' "${region}"
      done < <(jq -r '.regions[].id' "$(regions_json)")
      ;;
    explicit)
      jq -r '.sources.explicit[]' <<< "${config}"
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unsupported composite source mode: ${mode}" ;;
  esac
}

composite_source_regions_json() {
  local id="$1" config base
  config="$(composite_json "${id}")"
  base="$(composite_base_source_regions "${id}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
  jq -cn \
    --argjson base "${base}" \
    --argjson include "$(jq -c '.sources.include // []' <<< "${config}")" \
    --argjson exclude "$(jq -c '.sources.exclude // []' <<< "${config}")" \
    '($base + $include | unique | map(. as $region | select($exclude | index($region) | not)) | sort)' \
    | jq -e 'if length > 0 then . else error("composite source list is empty") end'
}

composite_source_regions() {
  composite_source_regions_json "$1" | jq -r '.[]'
}

composite_validate() {
  local id="$1" target config mode root provider override_region
  require_composite "${id}"
  config="$(composite_json "${id}")"
  target="$(jq -r '.target_region' <<< "${config}")"
  mode="$(jq -r '.sources.mode' <<< "${config}")"
  root="$(jq -r '.sources.root_region' <<< "${config}")"
  provider="$(jq -r '.inputs.provider' <<< "${config}")"

  jq -e --arg id "${id}" '
    .schema_version == 1
    and ([.composites[].id] | length == (unique | length))
    and (.composites[] | select(.id == $id)
      | (.target_region | type == "string" and length > 0)
      and (.sources.mode | IN("direct-children", "descendants", "explicit"))
      and (.sources.root_region | type == "string" and length > 0)
      and ((.sources.explicit // []) | type == "array" and all(.[]; type == "string"))
      and ((.sources.include // []) | type == "array" and all(.[]; type == "string"))
      and ((.sources.exclude // []) | type == "array" and all(.[]; type == "string"))
      and (.inputs.provider == "local-mirror")
      and (.inputs.basename_template == "{region-basename}-latest.osm.pbf")
      and ((.inputs.basename_overrides // {}) | type == "object")
      and ((.inputs.basename_overrides // {}) | all(.[]; type == "string" and test("^[A-Za-z0-9][A-Za-z0-9._-]*\\.osm\\.pbf$"))))
  ' "$(composites_json)" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "invalid composite configuration: ${id}"

  require_region "${target}"
  require_region "${root}"
  [[ "$(region_asset_role "${target}")" == "base-vector" ]] \
    || die "${HUAVD_EXIT_INPUT}" "composite target must be a base-vector region: ${target}"
  [[ "$(region_source_type "${target}")" == "osm-pbf" ]] \
    || die "${HUAVD_EXIT_INPUT}" "composite target must use osm-pbf source type: ${target}"
  [[ -n "$(region_stable_id "${target}")" && -n "$(role_source_id "${target}" base)" ]] \
    || die "${HUAVD_EXIT_INPUT}" "composite target has no registered map identity: ${target}"

  if [[ "${mode}" == "explicit" ]]; then
    [[ "$(jq -r '.sources.explicit | length' <<< "${config}")" -gt 0 ]] \
      || die "${HUAVD_EXIT_INPUT}" "explicit composite source list is empty: ${id}"
  fi

  while IFS= read -r region; do
    require_region "${region}"
  done < <(composite_source_regions "${id}")
  while IFS= read -r override_region; do
    require_region "${override_region}"
    composite_source_regions_json "${id}" | jq -e --arg region "${override_region}" 'index($region) != null' >/dev/null \
      || die "${HUAVD_EXIT_INPUT}" "composite basename override is not a resolved source region: ${override_region}"
  done < <(jq -r '.inputs.basename_overrides | keys[]' <<< "${config}")

  : "${provider}"
}

composite_pbf_basename() {
  local id="$1" region="$2" config template override basename
  config="$(composite_json "${id}")"
  template="$(jq -r '.inputs.basename_template' <<< "${config}")"
  override="$(jq -r --arg region "${region}" '.inputs.basename_overrides[$region] // empty' <<< "${config}")"
  basename="${override:-${template//\{region-basename\}/$(region_basename "${region}")}}"
  [[ "${basename}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.osm\.pbf$ ]] \
    || die "${HUAVD_EXIT_INPUT}" "invalid composite mirror basename for ${region}: ${basename}"
  printf '%s\n' "${basename}"
}

composite_cache_dir() {
  local id="$1"
  printf '%s/cache/merge/composites/%s\n' "${WORKDIR}" "${id}"
}
