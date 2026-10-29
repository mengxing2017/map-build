#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"
source "${SCRIPT_DIR}/lib/derived-map.sh"

DERIVED_MAP=""
FORCE=0
GLYPH="${GLYPH:-0}"
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --derived-map=*) DERIVED_MAP="${arg#*=}" ;;
    --glyph=*) GLYPH="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help) printf 'usage: %s --derived-map=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--glyph=0|1] [--force]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${DERIVED_MAP}" ]] || die "${HUAVD_EXIT_INPUT}" "--derived-map is required"
[[ "${GLYPH}" =~ ^[01]$ ]] || die "${HUAVD_EXIT_INPUT}" "--glyph must be 0 or 1"
require_cmd jq tippecanoe pmtiles
derived_map_validate "${DERIVED_MAP}"
REGION="$(derived_map_target_region "${DERIVED_MAP}")"
ROLE=base
normalize_session_vars

pmtiles="$(build_pmtiles_path base)"
if [[ -e "${pmtiles}" && "${FORCE}" != 1 ]]; then
  die "${HUAVD_EXIT_ERROR}" "output already exists: ${pmtiles}; pass --force or clean first"
fi
if [[ "${FORCE}" == 1 ]]; then
  rm -f "${pmtiles}" "${pmtiles}.sha512" "$(build_manifest_path base)" "$(build_attribution_path base)" "$(derived_map_report_path)"
fi

compose_args=(--derived-map="${DERIVED_MAP}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}")
[[ "${FORCE}" == 1 ]] && compose_args+=(--force)
"${SCRIPT_DIR}/compose-layers.sh" "${compose_args[@]}" >/dev/null

if [[ -n "$(effective_build_profile "${REGION}" base)" ]]; then
  layers_csv="$(effective_role_layers "${REGION}" base | paste -sd, -)"
  "${SCRIPT_DIR}/profile-transform.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --layers="${layers_csv}"
fi
"${SCRIPT_DIR}/tippecanoe.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=base --workdir="${WORKDIR}"
"${SCRIPT_DIR}/metadata.sh" --pmtiles="${pmtiles}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=base --workdir="${WORKDIR}"
"${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role=base --workdir="${WORKDIR}" --allow-missing-source

report="$(derived_map_report_path)"
report_sha512="$(sha512_value "${report}")"
manifest="$(build_manifest_path base)"
jq --slurpfile composition "${report}" --arg derived_map "${DERIVED_MAP}" --arg report_sha512 "${report_sha512}" '
  .source = {
    vendor: "derived-composition",
    source_type: "canonical-layer-features",
    composition: $composition[0],
    composition_report_sha512: $report_sha512
  }
  | .derived_map = {id:$derived_map,target_region:.region}
' "${manifest}" > "${manifest}.tmp"
mv "${manifest}.tmp" "${manifest}"

assets="$(derived_map_source_assets "${DERIVED_MAP}" | while IFS= read -r asset; do source_asset_json "${asset}" | jq -c '{id,provider,version,coverage,license_ref,priority}'; done | jq -s .)"
jq -n --argjson assets "${assets}" '{data_license:"ODbL-1.0",attribution:"© OpenStreetMap contributors",sources:$assets}' > "$(build_attribution_path base)"
write_sha512_file "${pmtiles}"
"${SCRIPT_DIR}/verify-derived-map.sh" --derived-map="${DERIVED_MAP}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --strict

if [[ "${GLYPH}" == 1 ]]; then
  "${SCRIPT_DIR}/glyph.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --force
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
printf 'build-derived-map: PASS %s\n' "${pmtiles}"
