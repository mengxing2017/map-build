#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd jq; overview_validate "${OVERVIEW}"
stage="$(overview_staging_dir "${OVERVIEW}" "${YYYYMMDD}")/layers"
while IFS= read -r layer; do
  input="${stage}/${layer}.geojsonseq"; require_file "${input}"; tmp="${input}.tmp"; allowed="$(layer_final_field_names_json "${layer}")"; post_filter="$(layer_post_filter_json "${layer}")"
  jq --seq -c --arg layer "${layer}" --argjson allowed "${allowed}" --argjson post_filter "${post_filter}" '
    def excluded($p): ($post_filter.exclude // {}) as $r | any($r | keys[]; . as $k | ($p[$k] // null) as $v | $v != null and ($r[$k] | index($v)));
    def geometry_allowed:
      (.geometry.type // "") as $type
      | ($post_filter.geometry // []) as $allowed_types
      | (($allowed_types | length) == 0 or ($allowed_types | index($type)) != null);
    def bbox_points:
      [.. | arrays | select(length == 2 and (.[0] | type) == "number" and (.[1] | type) == "number")];
    def bbox_center:
      bbox_points as $points
      | if ($points | length) == 0 then null else
          [((($points | map(.[0]) | min) + ($points | map(.[0]) | max)) / 2), ((($points | map(.[1]) | min) + ($points | map(.[1]) | max)) / 2)]
        end;
    def poi_area_label:
      .properties as $properties
      | ((["hospital", "clinic", "doctors", "school", "university", "college", "kindergarten"] | index($properties.amenity // "")) != null
         or (($properties.tourism // "") != ""));
    def normalize_point_geometry:
      if (($layer == "poi_label" and (.geometry.type != "Point") and poi_area_label)
          or ($layer == "highway_point" and (.geometry.type != "Point") and ((.properties.highway // "") | IN("services", "rest_area"))))
      then (.geometry.coordinates | bbox_center) as $center | if $center == null then empty else .geometry = {type:"Point",coordinates:$center} end
      else . end;
    if .properties then if excluded(.properties) or (geometry_allowed | not) then empty else
      normalize_point_geometry
      | .properties as $props
      | .properties.name = (["name:zh-Hans","name:zh","name","name:en"] | map($props[.]) | map(select(. != null and . != "")) | .[0])
      | if $layer == "waterway" then .properties.width = (.properties.width | if . == null then null else (try tonumber catch null) end) else . end
      | .properties |= with_entries(select((.key as $key | $allowed | index($key)) and .value != null)) end else . end
  ' "${input}" > "${tmp}" || die "${HUAVD_EXIT_ERROR}" "normalize failed for ${layer}"
  mv "${tmp}" "${input}"
done < <(overview_layers "${OVERVIEW}")
