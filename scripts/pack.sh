#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/install_json.sh
source "${SCRIPT_DIR}/lib/install_json.sh"

FORMAT="${FORMAT:-both}"
INCLUDE_BUILD_LOG=0

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --format=*) FORMAT="${arg#*=}" ;;
    --include-build-log) INCLUDE_BUILD_LOG=1 ;;
    -h|--help)
      printf 'usage: %s --session=<session> [--role=base|building|raster_bake|base_raster|both_raster|both|dem|all] [--format=tar|zip|both] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq tar zip sha256sum sha512sum
[[ -n "${SESSION}" ]] || die "${HUAVD_EXIT_INPUT}" "--session is required"
validate_session "${SESSION}"
YYYYMMDD="$(session_yyyymmdd "${SESSION}")"
ROLE="${ROLE:-both}"

case "${FORMAT}" in
  tar|zip|both) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid format: ${FORMAT}; expected tar, zip, or both" ;;
esac

out_dir="$(outputs_dir)"
pack_dir="$(pack_cache_dir)/${SESSION}"
pack_started_ms="$(epoch_millis)"
ensure_dir "${out_dir}"
rm -rf "${pack_dir}"
ensure_dir "${pack_dir}"

copied=0
roles_in_pack=()
prepare_started_ms="$(epoch_millis)"
while IFS= read -r role; do
  stem="${SESSION}.${role}"
  files=(
    "${out_dir}/${stem}.pmtiles"
    "${out_dir}/${stem}.pmtiles.sha512"
    "${out_dir}/${stem}.manifest.json"
    "${out_dir}/${stem}.attribution.json"
  )
  if [[ ! -f "${files[0]}" && "${ROLE}" == "both" && "${role}" == "building" ]]; then
    log_warn "skip missing optional building role for pack"
    continue
  fi
  if [[ ! -f "${files[0]}" && "${role}" == "dem" ]]; then
    if [[ "${ROLE}" != "dem" && "${ROLE}" != "all" ]] && ! dem_region_required "${REGION}"; then
      log_warn "skip missing optional DEM role for pack"
      continue
    fi
  fi
  for file in "${files[@]}"; do
    require_file "${file}"
    cp "${file}" "${pack_dir}/"
  done
  roles_in_pack+=("${role}")
  copied=$((copied + 1))
done < <(role_list "${ROLE}")

(( copied > 0 )) || die "${HUAVD_EXIT_INPUT}" "no artifacts copied for session=${SESSION} role=${ROLE}"

if (( INCLUDE_BUILD_LOG )); then
  find "${out_dir}" -maxdepth 1 -type f -name "BUILD-*.log" -exec cp {} "${pack_dir}/" \;
fi

copy_declared_assets() {
	  local style_file raster_style_file glyphs_dir sprite_dir
	  style_file="$(build_style_path)"
	  if [[ -f "${style_file}" ]]; then
	    rm -rf "${pack_dir}/styles"
	    ensure_dir "${pack_dir}/styles"
	    cp "${style_file}" "${style_file}.sha512" "${pack_dir}/styles/"
	  fi
	  raster_style_file="$(build_raster_style_path)"
	  if [[ -f "${raster_style_file}" ]]; then
	    ensure_dir "${pack_dir}/styles"
	    cp "${raster_style_file}" "${raster_style_file}.sha512" "${pack_dir}/styles/"
	  fi

  glyphs_dir="$(build_glyphs_dir)"
  if [[ -d "${glyphs_dir}" ]]; then
    rm -rf "${pack_dir}/glyphs"
    cp -R "${glyphs_dir}" "${pack_dir}/glyphs"
  fi

  sprite_dir="$(build_sprite_dir)"
  if [[ -d "${sprite_dir}" ]]; then
    rm -rf "${pack_dir}/sprite"
    cp -R "${sprite_dir}" "${pack_dir}/sprite"
  fi
}

if ((${#roles_in_pack[@]} > 0)); then
  if command -v jq >/dev/null 2>&1; then
    if offline_maps_json="$(install_offline_maps_json 0 "${roles_in_pack[@]}")"; then
      install_ensure_declared_outputs "${offline_maps_json}"
      copy_declared_assets
      bundle_id="$(install_manifest_value_for_roles bundle_id "${roles_in_pack[@]}")"
      activation="$(install_manifest_value_for_roles activation "${roles_in_pack[@]}")"
      bundle_id="${bundle_id:-$(install_default_bundle_id)}"
      activation="${activation:-manual}"
      install_write_document \
        "${pack_dir}/install.json" \
        "$(install_transfer_id)" \
        "${offline_maps_json}" \
        "$(install_region_for_roles "${roles_in_pack[@]}")" \
        "${bundle_id}" \
        "${activation}"
      install_require_declared_assets "${pack_dir}" "${offline_maps_json}"
      log_info "install descriptor OK: ${pack_dir}/install.json"
    else
      log_warn "skip install.json generation for pack: no valid install records"
    fi
  else
    log_warn "skip install.json generation for pack: jq is not available"
  fi
fi
prepare_elapsed_ms="$(( $(epoch_millis) - prepare_started_ms ))"

checksums_started_ms="$(epoch_millis)"
(
  cd -- "${pack_dir}"
  rm -f SHA256SUMS SHA512SUMS
  find . -type f ! -name SHA256SUMS ! -name SHA512SUMS ! -name '*.sha512' -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  find . -type f ! -name SHA256SUMS ! -name SHA512SUMS ! -name '*.sha512' -print0 \
    | sort -z \
    | while IFS= read -r -d '' file; do
        sidecar="${file}.sha512"
        if [[ -f "${sidecar}" ]]; then
          sha512="$(awk '{print $1; exit}' "${sidecar}")"
          printf '%s  %s\n' "${sha512}" "${file}"
        else
          sha512sum "${file}"
        fi
      done > SHA512SUMS
)
checksums_elapsed_ms="$(( $(epoch_millis) - checksums_started_ms ))"

tar_elapsed_ms=null
zip_elapsed_ms=null
tar_bytes=null
zip_bytes=null

if [[ "${FORMAT}" == "tar" || "${FORMAT}" == "both" ]]; then
  tar_started_ms="$(epoch_millis)"
  tar_path="${out_dir}/${SESSION}.bundle.tar.gz"
  tar -C "${pack_dir}" -czf "${tar_path}" . \
    || die "${HUAVD_EXIT_ERROR}" "tar pack failed: ${tar_path}"
  write_sha512_file "${tar_path}"
  tar_elapsed_ms="$(( $(epoch_millis) - tar_started_ms ))"
  tar_bytes="$(stat -c %s "${tar_path}")"
  printf '%s\n' "${tar_path}"
fi

if [[ "${FORMAT}" == "zip" || "${FORMAT}" == "both" ]]; then
  zip_started_ms="$(epoch_millis)"
  zip_path="${out_dir}/${SESSION}.bundle.zip"
  rm -f "${zip_path}"
  (
    cd -- "${pack_dir}"
    zip -qr "${zip_path}" .
  ) || die "${HUAVD_EXIT_ERROR}" "zip pack failed: ${zip_path}"
  write_sha512_file "${zip_path}"
  zip_elapsed_ms="$(( $(epoch_millis) - zip_started_ms ))"
  zip_bytes="$(stat -c %s "${zip_path}")"
  printf '%s\n' "${zip_path}"
fi

pack_file_count="$(find "${pack_dir}" -type f | wc -l | tr -d '[:space:]')"
pack_bytes="$(find "${pack_dir}" -type f -printf '%s\n' | awk '{sum += $1} END {print sum + 0}')"
pack_elapsed_ms="$(( $(epoch_millis) - pack_started_ms ))"
metrics_path="${out_dir}/${SESSION}.pack.metrics.json"
jq -n \
  --arg generated_at "$(timestamp_utc)" \
  --arg session "${SESSION}" \
  --arg role "${ROLE}" \
  --arg format "${FORMAT}" \
  --argjson copied_roles "${copied}" \
  --argjson pack_file_count "${pack_file_count}" \
  --argjson pack_bytes "${pack_bytes}" \
  --argjson prepare_ms "${prepare_elapsed_ms}" \
  --argjson checksums_ms "${checksums_elapsed_ms}" \
  --argjson tar_ms "${tar_elapsed_ms}" \
  --argjson zip_ms "${zip_elapsed_ms}" \
  --argjson total_ms "${pack_elapsed_ms}" \
  --argjson tar_bytes "${tar_bytes}" \
  --argjson zip_bytes "${zip_bytes}" \
  '{
    schema_version: 1,
    generated_at: $generated_at,
    session: $session,
    role: $role,
    format: $format,
    copied_roles: $copied_roles,
    pack_directory: {file_count: $pack_file_count, bytes: $pack_bytes},
    phases_ms: {prepare: $prepare_ms, checksums: $checksums_ms, tar: $tar_ms, zip: $zip_ms, total: $total_ms},
    archives: {tar_bytes: $tar_bytes, zip_bytes: $zip_bytes}
  }' > "${metrics_path}"
write_sha512_file "${metrics_path}"

log_info "pack metrics: ${metrics_path}"
log_info "pack OK: ${pack_dir}"
