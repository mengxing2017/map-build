#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

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
      printf 'usage: %s --region=<id> [--yyyymm=YYYYMM] [--workdir=<path>] [--locale=<tag>] [--pmtiles-url=<url>]\n' "$0"
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
style_path="$(build_style_path)"
ensure_dir "$(dirname -- "${style_path}")"

jq -n \
  --slurpfile config "${styles_config}" \
  --arg name "HUAVD offline vector style" \
  --arg source_id "${source_id}" \
  --arg source_type "${source_type}" \
  --arg source_url "${source_url}" \
  --arg glyphs_url "${glyphs_url}" \
  --arg locale "${STYLE_LOCALE}" \
  '
    ($config[0]) as $c
    | ($c.locales[] | select(.tag == $locale) | .name_fields) as $name_fields
    | def text_field($fields): ["coalesce"] + ($fields | map(["get", .]));
    {
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
        + ($c.text_layers | map({
          id: .id,
          type: "symbol",
          source: $source_id,
          "source-layer": .source_layer,
          minzoom: (.minzoom // 0),
          layout: {
            "text-field": text_field($name_fields),
            "text-font": (.font_stack // ["NotoSans-Regular"]),
            "text-size": (.text_size // 12),
            "text-anchor": "center"
          },
          paint: {
            "text-color": "#1f2933",
            "text-halo-color": "#ffffff",
            "text-halo-width": 1
          }
        }))
      ),
      metadata: {
        "huavd:style-locale": $locale
      }
    }
  ' > "${style_path}"

write_sha512_file "${style_path}"
log_info "style OK: ${style_path}"
