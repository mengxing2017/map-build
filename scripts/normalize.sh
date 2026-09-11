#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

LAYERS="all"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --layers=*) LAYERS="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--layers=all|layer[,layer...]] [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars

stage_layers="$(layers_dir)"
require_dir "${stage_layers}"
name_order="$(region_name_locale_priority_json "${REGION}")"

while IFS= read -r layer; do
  input="${stage_layers}/${layer}.geojsonseq"
  require_file "${input}"
  allowed="$(layer_final_field_names_json "${layer}")"
  post_filter="$(layer_post_filter_json "${layer}")"
  tmp="${input}.tmp"
  bak="${input}.bak"

  log_info "normalize ${layer}"
  jq --seq -c \
    --arg layer "${layer}" \
    --argjson name_order "${name_order}" \
    --argjson allowed "${allowed}" \
    --argjson post_filter "${post_filter}" \
    '
      def coalesced_name($props):
        ($name_order
          | map($props[.])
          | map(select(. != null and . != ""))
          | .[0]);
      def trim_name_separators:
        gsub("^[[:space:]()（）\\[\\]【】,，、/|·:：;；-]+"; "")
        | gsub("[[:space:]()（）\\[\\]【】,，、/|·:：;；-]+$"; "");
      def has_local_script:
        test("[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]");
      def has_latin:
        test("[A-Za-z]");
      def strip_english_suffix($english):
        if (($english // "") | type == "string" and length > 0) and endswith($english) then
          .[0:((length) - ($english | length))] | trim_name_separators
        else
          .
        end;
      def strip_trailing_latin:
        sub("[[:space:]()（）\\[\\]【】,，、/|·:：;；-]*[A-Za-z][A-Za-z0-9 .&/()\\-]+$"; "")
        | trim_name_separators;
      def clean_bilingual_name($props; $candidate):
        if ($candidate | type) == "string"
          and ($props.name // "") == $candidate
          and ($candidate | has_local_script)
          and ($candidate | has_latin)
        then
          (
            ($props["name:zh-Hans"] // $props["name:zh"])
            // (
              ($candidate | strip_english_suffix($props["name:en"])) as $without_en
              | if ($without_en != "" and $without_en != $candidate and ($without_en | has_local_script)) then
                  $without_en
                else
                  ($candidate | strip_trailing_latin) as $without_latin
                  | if ($without_latin != "" and $without_latin != $candidate and ($without_latin | has_local_script)) then
                      $without_latin
                    else
                      $candidate
                    end
                end
            )
          )
        else
          $candidate
        end;
      def excluded_by_post_filter($props):
        ($post_filter.exclude // {}) as $rules
        | ($rules | keys) as $fields
        | any($fields[]; . as $f | ($props[$f] // null) as $v | $v != null and ($rules[$f] | index($v)));
      def bbox_points:
        [.. | arrays | select(length == 2 and (.[0] | type) == "number" and (.[1] | type) == "number")];
      def bbox_center:
        (bbox_points) as $pts
        | if ($pts | length) == 0 then
            null
          else
            [
              (((($pts | map(.[0]) | min) + ($pts | map(.[0]) | max)) / 2)),
              (((($pts | map(.[1]) | min) + ($pts | map(.[1]) | max)) / 2))
            ]
          end;
      def key_amenity_area_label($props):
        ["hospital", "clinic", "doctors", "school", "university", "college", "kindergarten"] | index($props.amenity // "");
      def normalize_poi_label_geometry:
        if $layer == "poi_label"
          and (.geometry.type == "Polygon" or .geometry.type == "MultiPolygon")
          and key_amenity_area_label(.properties)
        then
          (.geometry.coordinates | bbox_center) as $center
          | if $center == null then empty else .geometry = {type: "Point", coordinates: $center} end
        else
          .
        end;
      def service_area_highway_point($props):
        ($props.highway // "") | IN("services", "rest_area");
      def normalize_highway_point_service_geometry:
        if $layer == "highway_point"
          and (.geometry.type != "Point")
          and service_area_highway_point(.properties)
        then
          (.geometry.coordinates | bbox_center) as $center
          | if $center == null then empty else .geometry = {type: "Point", coordinates: $center} end
        else
          .
        end;

      if .properties then
        if excluded_by_post_filter(.properties) then
          empty
        else
          normalize_poi_label_geometry
          | normalize_highway_point_service_geometry
          | .properties as $props
          | .properties.name = (coalesced_name($props) // $props.name)
          | .properties.name = clean_bilingual_name($props; .properties.name)
          | if $layer == "building" then
              .properties.type = (.properties.type // .properties.building)
              | .properties.levels = (.properties.levels // .properties["building:levels"])
              | .properties.roof_height = (.properties.roof_height // .properties["roof:height"])
            elif $layer == "waterway" then
              .properties.width = (.properties.width | if . == null then null else (try tonumber catch null) end)
            elif $layer == "peak" then
              .properties.ele = (.properties.ele | if . == null then null else (try tonumber catch null) end)
            else . end
          | .properties |= with_entries(select((.key as $key | $allowed | index($key)) and (.value != null)))
        end
      else
        .
      end
    ' "${input}" > "${tmp}" \
    || die "${HUAVD_EXIT_ERROR}" "normalize failed for layer ${layer}"

  mv "${input}" "${bak}"
  mv "${tmp}" "${input}"
done < <(selected_layers "${LAYERS}")

log_info "normalize OK: ${stage_layers}"
