#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_CONFIG_LOADED:-}" ]]; then
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
fi

derived_map_json() { jq -e --arg id "$1" '.composites[] | select(.id == $id)' "$(composites_json)"; }

require_derived_map() {
  [[ "$1" =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || die "${HUAVD_EXIT_INPUT}" "invalid derived map id: $1"
  derived_map_json "$1" >/dev/null || die "${HUAVD_EXIT_INPUT}" "derived map is not configured: $1"
}

derived_map_target_region() { derived_map_json "$1" | jq -r '.target_region'; }
derived_map_source_assets() { derived_map_json "$1" | jq -r '.sources[].asset'; }
derived_map_policy() { derived_map_json "$1" | jq -r '.conflict_policy'; }
derived_map_report_path() { printf '%s/%s.composition-report.json\n' "$(outputs_dir)" "${SESSION}"; }

derived_map_validate() {
  local map="$1" target policy profile asset
  require_derived_map "${map}"
  jq -e --arg id "${map}" '
    .schema_version == 2
    and ([.composites[].id] | length == (unique | length))
    and (.composites[] | select(.id == $id)
      | (.target_region | type == "string" and length > 0)
      and .layer_profile == "base-v1"
      and (.conflict_policy | type == "string" and length > 0)
      and (.sources | type == "array" and length > 0)
      and all(.sources[]; (.asset | type == "string") and .coverage_mode == "union"))
  ' "$(composites_json)" >/dev/null || die "${HUAVD_EXIT_INPUT}" "invalid derived map configuration: ${map}"
  target="$(derived_map_target_region "${map}")"
  require_region "${target}"
  [[ "$(region_asset_role "${target}")" == base-vector ]] || die "${HUAVD_EXIT_INPUT}" "derived target must be base-vector: ${target}"
  policy="$(derived_map_policy "${map}")"
  jq -e --arg id "${policy}" '.policies[] | select(.id == $id and .layer_profile == "base-v1" and .dedupe.mode == "exact-feature" and .precedence.mode == "source-order")' "$(conflict_policies_json)" >/dev/null \
    || die "${HUAVD_EXIT_INPUT}" "invalid conflict policy for derived map ${map}: ${policy}"
  while IFS= read -r asset; do source_asset_validate "${asset}"; done < <(derived_map_source_assets "${map}")
}
