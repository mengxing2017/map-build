#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/viewport.sh
source "${SCRIPT_DIR}/lib/viewport.sh"

STYLE_LOCALE="${STYLE_LOCALE:-}"
PMTILES_URL="${PMTILES_URL:-}"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --locale=*) STYLE_LOCALE="${arg#*=}" ;;
    --pmtiles-url=*) PMTILES_URL="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars

styles_config="$(styles_json)"
STYLE_LOCALE="${STYLE_LOCALE:-$(jq -r '.locales[0].tag' "${styles_config}")}"
jq -e --arg tag "${STYLE_LOCALE}" 'any(.locales[]; .tag == $tag)' "${styles_config}" >/dev/null \
  || die "${HUAVD_EXIT_INPUT}" "style locale is not configured: ${STYLE_LOCALE}"

source_id="$(jq -r '.source.id // "huavd-offline"' "${styles_config}")"
source_type="$(jq -r '.source.type // "vector"' "${styles_config}")"
source_url="${PMTILES_URL:-$(jq -r '.source.url // "pmtiles://{pmtiles}"' "${styles_config}")}"
glyphs_template="$(jq -r '.glyphs_url // "huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf"' "${styles_config}")"
glyphs_url="${glyphs_template//\{locale\}/${STYLE_LOCALE}}"
sprite_template="$(sprite_url)"
style_path="$(build_style_path)"
ensure_dir "$(dirname -- "${style_path}")"
effective_base_layers="$(effective_role_layers_json "${REGION}" base)"

base_pmtiles="$(build_pmtiles_path base)"
viewport_json="{}"
if [[ -f "${base_pmtiles}" ]]; then
  read -r center_lng center_lat weight < <(viewport_extract_center "${base_pmtiles}")
  default_zoom="$(viewport_calc_default_zoom "${base_pmtiles}")"
  viewport_json="$(jq -n \
    --argjson center "[${center_lng}, ${center_lat}]" \
    --argjson default_zoom "${default_zoom}" \
    --argjson min_zoom 0 \
    --argjson max_zoom 18 \
    '{center: $center, default_zoom: $default_zoom, min_zoom: $min_zoom, max_zoom: $max_zoom}')"
else
  log_warn "base.pmtiles not found, viewport metadata will be empty"
fi

jq -n \
  --slurpfile config "${styles_config}" \
  --arg name "HUAVD offline vector style" \
  --arg source_id "${source_id}" \
  --arg source_type "${source_type}" \
  --arg source_url "${source_url}" \
  --arg glyphs_url "${glyphs_url}" \
  --arg sprite_url "${sprite_template}" \
  --arg locale "${STYLE_LOCALE}" \
  --argjson viewport "${viewport_json}" \
  --argjson effective_base_layers "${effective_base_layers}" \
  '
    def text_field($fields): ["coalesce"] + ($fields | map(["get", .]));
    def convert_paint_value:
      if type == "object" and has("match") then
        .match as $m
        | ["match", ["get", $m.field]]
          + (reduce ($m.cases | to_entries[]) as $pair ([]; . + [$pair.key, $pair.value]))
          + [$m.default]
      else
        .
      end;
    def convert_paint_layer:
      . as $l
      | {
          id: $l.id,
          type: $l.type,
          source: $source_id,
          "source-layer": $l.source_layer,
          minzoom: ($l.minzoom // 0)
        }
        + (if ($l.layout // null) != null then {layout: ($l.layout | with_entries(.value |= convert_paint_value))} else {} end)
        + (if ($l.paint // null) != null then {paint: ($l.paint | with_entries(.value |= convert_paint_value))} else {} end)
        + (if ($l.filter // null) != null then {filter: $l.filter} else {} end);
    ($config[0]) as $c
    | ($c.locales[] | select(.tag == $locale)) as $locale_config
    | ($locale_config.name_fields) as $name_fields
    | (($locale_config.font_stack // ["NotoSans-Regular"]) | if type == "array" and length > 0 then . else ["NotoSans-Regular"] end) as $locale_font_stack
    | (($c.paint_layers // [])
      | map(select(.source_layer as $layer | $effective_base_layers | index($layer)))
      | map(convert_paint_layer)) as $paint_layers
    | {
      version: 8,
      name: $name,
      glyphs: $glyphs_url,
      sources: {
        ($source_id): {
          type: $source_type,
          url: $source_url
        }
      },
      layers: (
        [
          {
            id: "background",
            type: "background",
            paint: {"background-color": "#f4f2ed"}
          }
        ]
        + $paint_layers
        + ($c.text_layers
          | map(select(.source_layer as $layer | $effective_base_layers | index($layer)))
          | map({
          id: .id,
          type: "symbol",
          source: $source_id,
          "source-layer": .source_layer,
          minzoom: (.minzoom // 0),
          layout: ({
            "text-field": text_field($name_fields),
            "text-font": (.font_stack_by_locale[$locale] // $locale_font_stack // .font_stack // ["NotoSans-Regular"]),
            "text-size": (.text_size // 12),
            "text-anchor": "center",
            "text-allow-overlap": (.text_allow_overlap // false),
            "text-ignore-placement": (.text_ignore_placement // false),
            "text-optional": (.text_optional // false)
          }
          + (if .placement then {"symbol-placement": .placement} else {"symbol-placement": "point"} end)
          + (if .symbol_spacing then {"symbol-spacing": .symbol_spacing} else {} end)),
          paint: {
            "text-color": "#1f2933",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1
          }
        }))
      ),
      metadata: {
        "huavd:style-locale": $locale,
        "huavd:viewport": $viewport
      }
    }
    + (if $sprite_url == "" or $sprite_url == "null" then {} else {sprite: $sprite_url} end)
  ' > "${style_path}"

write_sha512_file "${style_path}"
log_info "style OK: ${style_path}"
