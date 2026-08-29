#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

INPUT=""
FORCE=0
GLYPH="${GLYPH:-0}"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --input=*) INPUT="${arg#*=}" ;;
    --glyph=*) GLYPH="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help)
      printf 'usage: %s --input=<path-to.osm.pbf> --region=<id> [--yyyymmdd=YYYYMMDD] [--role=base|building|both] [--workdir=<path>] [--glyph=0|1] [--force] [--force-building]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

ROLE="${ROLE:-both}"
case "${GLYPH}" in
  0|1) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid glyph flag: ${GLYPH}; expected 0 or 1" ;;
esac
require_cmd jq
require_region "${REGION}"
normalize_session_vars

[[ -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "--input is required"
INPUT="$(resolve_workspace_path "${INPUT}")"
if [[ ! -f "${INPUT}" ]]; then
  die "${HUAVD_EXIT_INPUT}" "required input PBF does not exist: ${INPUT}; run 'make fetch', place/rename/symlink the PBF to this path, or set INPUT=/path/to/input.osm.pbf for manually downloaded files"
fi
require_cmd osmium tippecanoe pmtiles sha512sum

ensure_dir "$(outputs_dir)"
ensure_dir "$(tags_filter_cache_dir)"
ensure_dir "$(layers_dir)"

cleanup_role_artifacts() {
  local role="$1"
  local output
  output="$(build_pmtiles_path "${role}")"
  rm -f \
    "${output}" \
    "${output}.sha512" \
    "$(build_manifest_path "${role}")" \
    "$(build_attribution_path "${role}")"
}

role_artifacts_complete() {
  local role="$1"
  local output
  output="$(build_pmtiles_path "${role}")"
  [[ -f "${output}" \
    && -f "${output}.sha512" \
    && -f "$(build_manifest_path "${role}")" \
    && -f "$(build_attribution_path "${role}")" ]]
}

role_artifacts_exist() {
  local role="$1"
  local output
  output="$(build_pmtiles_path "${role}")"
  [[ -e "${output}" \
    || -e "${output}.sha512" \
    || -e "$(build_manifest_path "${role}")" \
    || -e "$(build_attribution_path "${role}")" ]]
}

write_building_skip_report() {
  local report_file
  report_file="$(report_dir)/${YYYYMMDD}-building-role-skip.md"
  ensure_dir "$(report_dir)"
  local actual_asset_role actual_source_type
  actual_asset_role="$(region_asset_role "${REGION}" 2>/dev/null || printf '(unset)')"
  actual_source_type="$(region_source_type "${REGION}" 2>/dev/null || printf '(unset)')"
  cat > "${report_file}" <<EOF
# Building Role Skip Report

**Date**: $(date -u +%Y-%m-%d)
**Region**: ${REGION}
**Session**: ${SESSION}

## Summary

The building role was skipped because the region configuration does not meet the requirements.

## Configuration

| Field | Current Value | Required Value |
|-------|--------------|----------------|
| \`asset_role\` | \`${actual_asset_role}\` | \`building-vector\` |
| \`source_type\` | \`${actual_source_type}\` | \`derived-building\` |

## How to Enable

Update \`config/regions.yaml\` for this region:

\`\`\`yaml
huavd:
  asset_role: "building-vector"
  source_type: "derived-building"
\`\`\`
EOF
  log_info "building skip report written: ${report_file}"
}

roles_to_build=()
while IFS= read -r role; do
  if [[ "${role}" == "building" ]] && ! building_role_allowed "${REGION}"; then
    if [[ "${ROLE}" == "building" ]]; then
      die "${HUAVD_EXIT_INPUT}" "building role is not enabled for region ${REGION} in regions.yaml (pass --force-building to override)"
    fi
    log_warn "skip building role: regions.yaml does not mark ${REGION} as building-vector/derived-building"
    write_building_skip_report
    continue
  fi
  output="$(build_pmtiles_path "${role}")"
  if role_artifacts_complete "${role}" && [[ "${FORCE}" != "1" ]]; then
    die "${HUAVD_EXIT_ERROR}" "output already exists: ${output}; pass --force or clean first"
  fi
  if role_artifacts_exist "${role}"; then
    if [[ "${FORCE}" == "1" ]]; then
      cleanup_role_artifacts "${role}"
    else
      log_warn "remove incomplete output artifacts from previous failed build: ${output}"
      cleanup_role_artifacts "${role}"
    fi
  fi
  roles_to_build+=("${role}")
done < <(role_list "${ROLE}")

((${#roles_to_build[@]} > 0)) || die "${HUAVD_EXIT_INPUT}" "no buildable roles for region=${REGION} role=${ROLE}"

declare -A preprocess_seen=()
preprocess_layers=()
for role in "${roles_to_build[@]}"; do
  while IFS= read -r layer; do
    if [[ -z "${preprocess_seen[${layer}]:-}" ]]; then
      preprocess_seen["${layer}"]=1
      preprocess_layers+=("${layer}")
    fi
  done < <(effective_role_layers "${REGION}" "${role}")
done
preprocess_layers_csv="$(IFS=,; printf '%s' "${preprocess_layers[*]}")"

source_link="$(staging_dir)/source.osm.pbf"
ln -sf "${INPUT}" "${source_link}"
log_info "source linked: ${source_link} -> ${INPUT}"

"${SCRIPT_DIR}/tags-filter.sh" --input="${source_link}" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --layers="${preprocess_layers_csv}"
"${SCRIPT_DIR}/export.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --layers="${preprocess_layers_csv}"
"${SCRIPT_DIR}/normalize.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --layers="${preprocess_layers_csv}"

if [[ " ${roles_to_build[*]} " == *" base " ]] && [[ -n "$(effective_build_profile "${REGION}" base)" ]]; then
  base_layers_csv="$(effective_role_layers "${REGION}" base | paste -sd, -)"
  "${SCRIPT_DIR}/profile-transform.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --layers="${base_layers_csv}"
fi

for role in "${roles_to_build[@]}"; do
  "${SCRIPT_DIR}/tippecanoe.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/metadata.sh" --pmtiles="$(build_pmtiles_path "${role}")" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/attribution.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role="${role}" --workdir="${WORKDIR}"
  write_sha512_file "$(build_pmtiles_path "${role}")"
  "${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --role="${role}" --workdir="${WORKDIR}"
  printf 'build OK: %s\n' "$(build_pmtiles_path "${role}")"
done

if [[ "${GLYPH}" == "1" ]]; then
  "${SCRIPT_DIR}/glyph.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" --force
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
