#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; source "${SCRIPT_DIR}/lib/common.sh"; source "${SCRIPT_DIR}/lib/config.sh"; source "${SCRIPT_DIR}/lib/composite.sh"
COMPOSITE="" FORCE=0 GLYPH="${GLYPH:-0}"
for arg in "$@"; do if parse_common_arg "${arg}"; then continue; fi; case "${arg}" in --composite=*) COMPOSITE="${arg#*=}";; --force) FORCE=1;; --glyph=*) GLYPH="${arg#*=}";; -h|--help) printf 'usage: %s --composite=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--glyph=0|1] [--force]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${COMPOSITE}" ]] || die "${HUAVD_EXIT_INPUT}" "--composite is required"; [[ "${GLYPH}" =~ ^[01]$ ]] || die "${HUAVD_EXIT_INPUT}" "--glyph must be 0 or 1"; composite_validate "${COMPOSITE}"; REGION="$(composite_target_region "${COMPOSITE}")"; normalize_session_vars
merge_args=(--composite="${COMPOSITE}" --workdir="${WORKDIR}"); [[ "${FORCE}" == 1 ]] && merge_args+=(--force); merged="$("${SCRIPT_DIR}/merge-composite-pbf.sh" "${merge_args[@]}")"
build_args=(--input="${merged}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=base --workdir="${WORKDIR}" --glyph="${GLYPH}"); [[ "${FORCE}" == 1 ]] && build_args+=(--force); "${SCRIPT_DIR}/build.sh" "${build_args[@]}"
fingerprint="$(basename -- "${merged}" .osm.pbf)"; lineage="$(composite_cache_dir "${COMPOSITE}")/${fingerprint}.json"; manifest="$(build_manifest_path base)"; require_file "${lineage}"; require_file "${manifest}"
jq --slurpfile lineage "${lineage}" --arg fingerprint "${fingerprint}" --arg composite "${COMPOSITE}" '.source={vendor:"local-mirror",source_type:"osm-pbf",composition:($lineage[0]+{method:"osmium-merge",fingerprint:$fingerprint})}|.composite={id:$composite,target_region:.region}' "${manifest}" > "${manifest}.tmp"; mv "${manifest}.tmp" "${manifest}"
"${SCRIPT_DIR}/verify-composite.sh" --composite="${COMPOSITE}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --strict
