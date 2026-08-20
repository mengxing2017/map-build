#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/install_json.sh
source "${SCRIPT_DIR}/lib/install_json.sh"

OUTPUT_PATH=""
FORMAT="${FORMAT:-}"
TRANSFER_ID=""
AGGREGATE_MANIFEST="${AGGREGATE_MANIFEST:-0}"

resolve_import_output_path() {
  local path="$1"
  if is_abs_path "${path}"; then
    printf '%s\n' "${path}"
  else
    printf '%s/%s\n' "${WORKDIR}" "${path}"
  fi
}

infer_import_format() {
  local path="$1"
  case "${path}" in
    *.tar.gz|*.tgz) printf 'tar\n' ;;
    *.zip) printf 'zip\n' ;;
    *) return 1 ;;
  esac
}

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --output=*) OUTPUT_PATH="${arg#*=}" ;;
    --format=*) FORMAT="${arg#*=}" ;;
    --transfer-id=*) TRANSFER_ID="${arg#*=}" ;;
    --aggregate) AGGREGATE_MANIFEST="1" ;;
    --aggregate=true) AGGREGATE_MANIFEST="1" ;;
    --aggregate=false) AGGREGATE_MANIFEST="0" ;;
    -h|--help)
      printf 'usage: %s --session=<session> [--role=base|building|both] [--format=tar|zip] [--output=<archive-path>] [--transfer-id=<id>] [--aggregate] [--workdir=<path>] [--region=<id>] [--yyyymmdd=YYYYMMDD]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

ROLE="${ROLE:-base}"
require_cmd jq sha512sum
require_region "${REGION}"
normalize_session_vars
role_list "${ROLE}" >/dev/null
import_dir="$(import_cache_dir)/${SESSION}"

if [[ -n "${OUTPUT_PATH}" && -z "${FORMAT}" ]]; then
  FORMAT="$(infer_import_format "${OUTPUT_PATH}")" \
    || die "${HUAVD_EXIT_INPUT}" "cannot infer import format from output path: ${OUTPUT_PATH}; expected .tar.gz, .tgz, or .zip"
fi
FORMAT="${FORMAT:-zip}"
case "${FORMAT}" in
  tar|zip) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid import format: ${FORMAT}; expected tar or zip" ;;
esac
case "${FORMAT}" in
  tar) require_cmd tar ;;
  zip) require_cmd zip ;;
esac

if [[ -z "${OUTPUT_PATH}" ]]; then
  ensure_dir "$(outputs_dir)"
  case "${FORMAT}" in
    tar) OUTPUT_PATH="$(outputs_dir)/${SESSION}.import.tar.gz" ;;
    zip) OUTPUT_PATH="$(outputs_dir)/${SESSION}.import.zip" ;;
  esac
else
  OUTPUT_PATH="$(resolve_import_output_path "${OUTPUT_PATH}")"
fi
inferred_format="$(infer_import_format "${OUTPUT_PATH}")" \
  || die "${HUAVD_EXIT_INPUT}" "import output must end with .tar.gz, .tgz, or .zip: ${OUTPUT_PATH}"
if [[ "${inferred_format}" != "${FORMAT}" ]]; then
  die "${HUAVD_EXIT_INPUT}" "import output extension does not match format=${FORMAT}: ${OUTPUT_PATH}"
fi
case "${OUTPUT_PATH}" in
  */) die "${HUAVD_EXIT_INPUT}" "import output must be a compressed archive file path, not a directory: ${OUTPUT_PATH}" ;;
esac
if [[ -d "${OUTPUT_PATH}" ]]; then
  die "${HUAVD_EXIT_INPUT}" "import output must be a compressed archive file path, not a directory: ${OUTPUT_PATH}"
fi
if [[ "${OUTPUT_PATH}" == "${import_dir}/"* ]]; then
  die "${HUAVD_EXIT_INPUT}" "import output must not be inside the import cache directory: ${OUTPUT_PATH}"
fi

if [[ -z "${TRANSFER_ID}" ]]; then
  TRANSFER_ID="$(install_transfer_id)"
fi
[[ "${TRANSFER_ID}" =~ ^[A-Za-z0-9._-]+$ ]] \
  || die "${HUAVD_EXIT_INPUT}" "invalid transfer-id: ${TRANSFER_ID}; expected a safe path segment"

roles_to_prepare=()
while IFS= read -r role; do
  pmtiles="$(build_pmtiles_path "${role}")"
  if [[ ! -f "${pmtiles}" && "${ROLE}" == "both" && "${role}" == "building" ]]; then
    log_warn "skip missing optional building role for prepare-import"
    continue
  fi
  require_file "${pmtiles}"
  require_file "$(build_manifest_path "${role}")"
  require_file "$(build_sha512_path "${role}")"
  roles_to_prepare+=("${role}")
done < <(role_list "${ROLE}")

((${#roles_to_prepare[@]} > 0)) \
  || die "${HUAVD_EXIT_INPUT}" "no artifacts available for prepare-import session=${SESSION} role=${ROLE}"

offline_maps_json="$(install_offline_maps_json 1 "${roles_to_prepare[@]}")"
document_region="$(install_region_for_roles "${roles_to_prepare[@]}")"
bundle_id="$(install_manifest_value_for_roles bundle_id "${roles_to_prepare[@]}")"
activation="$(install_manifest_value_for_roles activation "${roles_to_prepare[@]}")"
bundle_id="${bundle_id:-$(install_default_bundle_id)}"
activation="${activation:-manual}"

staging_dir="${import_dir}/.staging/${TRANSFER_ID}"
install_json="${import_dir}/install.json"
rm -rf "${import_dir}"
ensure_dir "${staging_dir}"
ensure_dir "$(dirname -- "${OUTPUT_PATH}")"

while IFS= read -r entry; do
  file_name="$(jq -r '.file' <<< "${entry}")"
  expected_sha="$(jq -r '.checksum.value' <<< "${entry}")"
  source_file="$(outputs_dir)/${file_name}"
  target_file="${staging_dir}/${file_name}"

  require_file "${source_file}"
  cp "${source_file}" "${target_file}" \
    || die "${HUAVD_EXIT_DISK}" "failed to copy PMTiles into import staging: ${target_file}"

  actual_sha="$(sha512_value "${target_file}")"
  [[ "${actual_sha}" == "${expected_sha}" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "staged PMTiles sha512 mismatch: ${target_file}"
done < <(jq -c '.[]' <<< "${offline_maps_json}")

case "${AGGREGATE_MANIFEST}" in
  0) install_write_document "${install_json}" "${TRANSFER_ID}" "${offline_maps_json}" "${document_region}" "${bundle_id}" "${activation}" ;;
  1) install_write_aggregate_document "${install_json}" "${TRANSFER_ID}" "${offline_maps_json}" "${document_region}" "${bundle_id}" "${activation}" ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid aggregate manifest mode: ${AGGREGATE_MANIFEST}" ;;
esac

install_ensure_declared_outputs "${offline_maps_json}"

style_file="$(build_style_path)"
if [[ -f "${style_file}" ]]; then
  ensure_dir "${import_dir}/styles"
  cp "${style_file}" "${style_file}.sha512" "${import_dir}/styles/" \
    || die "${HUAVD_EXIT_DISK}" "failed to copy style into import package"
fi

glyphs_dir="$(build_glyphs_dir)"
if [[ -d "${glyphs_dir}" ]]; then
  cp -R "${glyphs_dir}" "${import_dir}/glyphs" \
    || die "${HUAVD_EXIT_DISK}" "failed to copy glyphs into import package"
fi

sprite_dir="$(build_sprite_dir)"
if [[ -d "${sprite_dir}" ]]; then
  cp -R "${sprite_dir}" "${import_dir}/sprite" \
    || die "${HUAVD_EXIT_DISK}" "failed to copy sprite into import package"
fi

install_require_declared_assets "${import_dir}" "${offline_maps_json}"

case "${FORMAT}" in
  tar)
    tar -C "${import_dir}" -czf "${OUTPUT_PATH}" . \
      || die "${HUAVD_EXIT_ERROR}" "tar import package failed: ${OUTPUT_PATH}"
    ;;
  zip)
    rm -f "${OUTPUT_PATH}"
    (
      cd -- "${import_dir}"
      zip -qr "${OUTPUT_PATH}" .
    ) || die "${HUAVD_EXIT_ERROR}" "zip import package failed: ${OUTPUT_PATH}"
    ;;
esac
write_sha512_file "${OUTPUT_PATH}"

printf 'prepare-import OK: %s\n' "${OUTPUT_PATH}"
printf 'archive: %s\n' "${OUTPUT_PATH}"
printf 'archive_sha512: %s.sha512\n' "${OUTPUT_PATH}"
printf 'install.json: %s\n' "${install_json}"
printf 'transfer_id: %s\n' "${TRANSFER_ID}"
printf 'staging: %s\n' "${staging_dir}"
jq -r '.offline_maps[] | "offline-map id=\(.id) name=\(.name) file=\(.file) checksum=\(.checksum.value)"' "${install_json}"
