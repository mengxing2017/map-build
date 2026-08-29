#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW="" INPUT=""; for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --input=*) INPUT="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; -h|--help) printf 'usage: %s --overview=<id> --input=<pbf> [--yyyymmdd=YYYYMMDD] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" && -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview and --input are required"
validate_yyyymmdd "${YYYYMMDD}"; require_cmd osmium jq; overview_validate "${OVERVIEW}"; require_file "${INPUT}"
cache_dir="$(overview_filter_cache_dir "${OVERVIEW}")/$(sha512_value "${INPUT}")"; ensure_dir "${cache_dir}"
while IFS= read -r layer; do mapfile -t filters < <(layer_tags_filter_args "${layer}"); osmium tags-filter -O -o "${cache_dir}/${layer}.osm.pbf" "${INPUT}" "${filters[@]}" || die "${HUAVD_EXIT_ERROR}" "tags-filter failed for ${layer}"; done < <(overview_layers "${OVERVIEW}")
