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
    if .properties then if excluded(.properties) then empty else
      .properties.name = (["name:zh-Hans","name:zh","name","name:en"] | map(. as $k | .properties[$k]) | map(select(. != null and . != "")) | .[0])
      | if $layer == "waterway" then .properties.width = (.properties.width | if . == null then null else (try tonumber catch null) end) else . end
      | .properties |= with_entries(select(($allowed | index(.key)) and .value != null)) end else . end
  ' "${input}" > "${tmp}" || die "${HUAVD_EXIT_ERROR}" "normalize failed for ${layer}"
  mv "${tmp}" "${input}"
done < <(overview_layers "${OVERVIEW}")
