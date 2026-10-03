#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP=""
STRICT=0
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    --strict) STRICT=1 ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--strict]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
require_cmd jq
derived_map_validate "${DERIVED_MAP}"
REGION="$(derived_map_target_region "${DERIVED_MAP}")"
ROLE=base
normalize_session_vars
verify_args=(--region="${REGION}" --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --role=base --workdir="${WORKDIR}")
[[ "${STRICT}" == 1 ]] && verify_args+=(--strict)
"${SCRIPT_DIR}/verify.sh" "${verify_args[@]}"
report="$(derived_map_report_path)"
manifest="$(build_manifest_path base)"
require_file "${report}"
jq -e --arg map "${DERIVED_MAP}" --arg region "${REGION}" --arg policy "$(derived_map_policy "${DERIVED_MAP}")" --arg report_sha512 "$(sha512_value "${report}")" '
  .derived_map.id == $map
  and .derived_map.target_region == $region
  and .source.vendor == "derived-composition"
  and .source.source_type == "canonical-layer-features"
  and .source.composition.derived_map == $map
  and .source.composition.target_region == $region
  and .source.composition.conflict_policy == $policy
  and .source.composition_report_sha512 == $report_sha512
' "${manifest}" >/dev/null || die "${HUAVD_EXIT_VERIFY}" "derived manifest does not match composition report"
printf 'verify-derived-map: PASS\n'
