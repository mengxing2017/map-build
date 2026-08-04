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
      printf 'usage: %s --input=<path-to.osm.pbf> --region=<id> [--yyyymm=YYYYMM] [--role=base|building|both] [--workdir=<path>] [--glyph=0|1] [--force]\n' "$0"
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

roles_to_build=()
while IFS= read -r role; do
  if [[ "${role}" == "building" ]] && ! building_role_enabled "${REGION}"; then
    if [[ "${ROLE}" == "building" ]]; then
      die "${HUAVD_EXIT_INPUT}" "building role is not enabled for region ${REGION} in regions.yaml"
    fi
    log_warn "skip building role: regions.yaml does not mark ${REGION} as building-vector/derived-building"
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

preprocess_layers="all"
if ((${#roles_to_build[@]} == 1)) && [[ "${roles_to_build[0]}" == "building" ]]; then
  preprocess_layers="building"
fi

source_link="$(staging_dir)/source.osm.pbf"
ln -sf "${INPUT}" "${source_link}"
log_info "source linked: ${source_link} -> ${INPUT}"

"${SCRIPT_DIR}/tags-filter.sh" --input="${source_link}" --region="${REGION}" --yyyymm="${YYYYMM}" --workdir="${WORKDIR}" --layers="${preprocess_layers}"
"${SCRIPT_DIR}/export.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --workdir="${WORKDIR}" --layers="${preprocess_layers}"
"${SCRIPT_DIR}/normalize.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --workdir="${WORKDIR}" --layers="${preprocess_layers}"

for role in "${roles_to_build[@]}"; do
  "${SCRIPT_DIR}/tippecanoe.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/metadata.sh" --pmtiles="$(build_pmtiles_path "${role}")" --region="${REGION}" --yyyymm="${YYYYMM}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/manifest.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --role="${role}" --workdir="${WORKDIR}"
  "${SCRIPT_DIR}/attribution.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --role="${role}" --workdir="${WORKDIR}"
  write_sha512_file "$(build_pmtiles_path "${role}")"
  "${SCRIPT_DIR}/verify.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --role="${role}" --workdir="${WORKDIR}"
  printf 'build OK: %s\n' "$(build_pmtiles_path "${role}")"
done

if [[ "${GLYPH}" == "1" ]]; then
  "${SCRIPT_DIR}/glyph.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --workdir="${WORKDIR}" --force
  "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymm="${YYYYMM}" --workdir="${WORKDIR}"
fi
