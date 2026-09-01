#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; source "${SCRIPT_DIR}/lib/common.sh"; source "${SCRIPT_DIR}/lib/config.sh"; source "${SCRIPT_DIR}/lib/composite.sh"
COMPOSITE="" STRICT=0
for arg in "$@"; do if parse_common_arg "${arg}"; then continue; fi; case "${arg}" in --composite=*) COMPOSITE="${arg#*=}";; --strict) STRICT=1;; -h|--help) printf 'usage: %s --composite=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--workdir=<path>] [--strict]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${COMPOSITE}" ]] || die "${HUAVD_EXIT_INPUT}" "--composite is required"; composite_validate "${COMPOSITE}"; REGION="$(composite_target_region "${COMPOSITE}")"; normalize_session_vars
args=(--region="${REGION}" --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --role=base --workdir="${WORKDIR}"); [[ "${STRICT}" == 1 ]] && args+=(--strict); "${SCRIPT_DIR}/verify.sh" "${args[@]}"
manifest="$(build_manifest_path base)"; sources="$(composite_source_regions_json "${COMPOSITE}")"
jq -e --arg composite "${COMPOSITE}" --arg region "${REGION}" --arg source_id "$(role_source_id "${REGION}" base)" --arg region_id "$(region_stable_id "${REGION}")" --argjson sources "${sources}" '.composite.id==$composite and .composite.target_region==$region and .source.vendor=="local-mirror" and .source.composition.method=="osmium-merge" and (.source.composition.source_regions==$sources) and ([.source.composition.inputs[].region]|sort==$sources) and .huavd_record.id==$region_id and .huavd_record.source_id==$source_id and .huavd_record.asset_role=="base-vector"' "${manifest}" >/dev/null || die "${HUAVD_EXIT_VERIFY}" "composite manifest does not match configured target identity or sources"
printf 'verify-composite: PASS\n'
