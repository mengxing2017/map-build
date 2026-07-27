#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"

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
      printf 'usage: %s --session=<session> [--role=base|building|both] [--format=tar|zip|both] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd tar zip sha256sum sha512sum
[[ -n "${SESSION}" ]] || die "${HUAVD_EXIT_INPUT}" "--session is required"
validate_session "${SESSION}"
YYYYMM="$(session_yyyymm "${SESSION}")"
ROLE="${ROLE:-both}"

case "${FORMAT}" in
  tar|zip|both) ;;
  *) die "${HUAVD_EXIT_INPUT}" "invalid format: ${FORMAT}; expected tar, zip, or both" ;;
esac

out_dir="$(outputs_dir)"
pack_dir="$(pack_cache_dir)/${SESSION}"
ensure_dir "${out_dir}"
rm -rf "${pack_dir}"
ensure_dir "${pack_dir}"

copied=0
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
  for file in "${files[@]}"; do
    require_file "${file}"
    cp "${file}" "${pack_dir}/"
  done
  copied=$((copied + 1))
done < <(role_list "${ROLE}")

(( copied > 0 )) || die "${HUAVD_EXIT_INPUT}" "no artifacts copied for session=${SESSION} role=${ROLE}"

if (( INCLUDE_BUILD_LOG )); then
  find "${out_dir}" -maxdepth 1 -type f -name "BUILD-*.log" -exec cp {} "${pack_dir}/" \;
fi

(
  cd -- "${pack_dir}"
  rm -f SHA256SUMS
  sha256sum * > SHA256SUMS
)

if [[ "${FORMAT}" == "tar" || "${FORMAT}" == "both" ]]; then
  tar_path="${out_dir}/${SESSION}.bundle.tar.gz"
  tar -C "${pack_dir}" -czf "${tar_path}" . \
    || die "${HUAVD_EXIT_ERROR}" "tar pack failed: ${tar_path}"
  write_sha512_file "${tar_path}"
  printf '%s\n' "${tar_path}"
fi

if [[ "${FORMAT}" == "zip" || "${FORMAT}" == "both" ]]; then
  zip_path="${out_dir}/${SESSION}.bundle.zip"
  rm -f "${zip_path}"
  (
    cd -- "${pack_dir}"
    zip -qr "${zip_path}" .
  ) || die "${HUAVD_EXIT_ERROR}" "zip pack failed: ${zip_path}"
  write_sha512_file "${zip_path}"
  printf '%s\n' "${zip_path}"
fi

log_info "pack OK: ${pack_dir}"
