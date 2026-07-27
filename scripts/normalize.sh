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
      printf 'usage: %s --region=<id> [--layers=all|layer[,layer...]] [--workdir=<path>] [--yyyymm=YYYYMM]\n' "$0"
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
name_order="$(jq -c '.global.name_coalesce_order' "$(layers_json)")"

while IFS= read -r layer; do
  input="${stage_layers}/${layer}.geojsonseq"
  require_file "${input}"
  allowed="$(layer_final_field_names_json "${layer}")"
  tmp="${input}.tmp"
  bak="${input}.bak"

  log_info "normalize ${layer}"
  jq --seq -c \
    --arg layer "${layer}" \
    --argjson name_order "${name_order}" \
    --argjson allowed "${allowed}" \
    '
      def coalesced_name($props):
        ($name_order
          | map($props[.])
          | map(select(. != null and . != ""))
          | .[0]);

      if .properties then
        if $layer == "natural_a" and .properties.natural == "water" then
          empty
        else
          .properties as $props
          | .properties.name = (coalesced_name($props) // $props.name)
          | if $layer == "building" then
              .properties.type = (.properties.type // .properties.building)
              | .properties.levels = (.properties.levels // .properties["building:levels"])
              | .properties.roof_height = (.properties.roof_height // .properties["roof:height"])
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
