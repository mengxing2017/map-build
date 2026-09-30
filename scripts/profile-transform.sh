#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

LAYERS=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --layers=*) LAYERS="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --layers=<layer[,layer...]> [--workdir=<path>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars
[[ -n "${LAYERS}" && "${LAYERS}" != "all" ]] \
  || die "${HUAVD_EXIT_INPUT}" "--layers must name the effective base layers"

profile="$(effective_build_profile "${REGION}" base)"
[[ -n "${profile}" ]] || {
  log_info "no build profile for ${REGION}; skip profile transform"
  exit 0
}

expected_layers="$(effective_role_layers_json "${REGION}" base)"
actual_layers="$(selected_layers "${LAYERS}" | jq -Rsc 'split("\n") | map(select(length > 0))')"
[[ "$(jq -cS . <<< "${actual_layers}")" == "$(jq -cS . <<< "${expected_layers}")" ]] \
  || die "${HUAVD_EXIT_INPUT}" "profile transform layers do not match effective base layers"

stage_layers="$(layers_dir)"
profile_json="$(tier_profile_json "${profile}")"

while IFS= read -r layer; do
  rules="$(jq -c --arg layer "${layer}" '.feature_rules[$layer] // null' <<< "${profile_json}")"
  input="${stage_layers}/${layer}.geojsonseq"
  tmp="${input}.profile.tmp"
  min_zoom="$(effective_layer_min_zoom "${REGION}" base "${layer}")"
  max_zoom="$(effective_layer_max_zoom "${REGION}" base "${layer}" "$(jq -r '.max_zoom' <<< "${profile_json}")")"
  require_file "${input}"
  [[ -s "${input}" ]] || continue

  log_info "profile transform ${profile} ${layer}"
  jq --seq -c --arg layer "${layer}" --argjson rules "${rules}" --argjson min_zoom "${min_zoom}" --argjson max_zoom "${max_zoom}" '
    def rule_matches($properties; $rule):
      ($rule.when | to_entries
        | all(.[]; . as $entry | ($properties[$entry.key] // null) as $value | ($entry.value | index($value)) != null));
    def selected_rule($properties):
      first($rules.rules[] | select(rule_matches($properties; .)));
    def intersect_zoom($existing; $profile_min; $profile_max):
      ($existing.minzoom // $profile_min) as $existing_min
      | ($existing.maxzoom // $profile_max) as $existing_max
      | {minzoom: [$existing_min, $profile_min] | max,
         maxzoom: [$existing_max, $profile_max] | min};

    if (.type == "Feature" and (.properties | type == "object")) then
      if $rules == null then
        .tippecanoe = ((.tippecanoe // {}) + {minzoom: $min_zoom, maxzoom: $max_zoom})
      else
      selected_rule(.properties) as $rule
      | if $rule == null then
          empty
        else
          # These layers may already carry a hierarchy-specific zoom range.
          # Keep the profile selection while preserving that narrower range.
          if ($layer == "place_label" or $layer == "admin_line") and (.tippecanoe | type == "object") then
            (.tippecanoe | intersect_zoom(.; $rule.min_zoom; $rule.max_zoom)) as $zoom
            | if $zoom.minzoom <= $zoom.maxzoom then .tippecanoe = $zoom else empty end
          else
            .tippecanoe = ((.tippecanoe // {}) + {minzoom: $rule.min_zoom, maxzoom: $rule.max_zoom})
          end
        end
      end
    else
      .
    end
  ' "${input}" > "${tmp}" \
    || die "${HUAVD_EXIT_ERROR}" "profile transform failed for layer ${layer}"
  mv "${tmp}" "${input}"
done < <(effective_role_layers "${REGION}" base)

log_info "profile transform OK: ${profile}"
