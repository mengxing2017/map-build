#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

LIMIT_RATE="${LIMIT_RATE:-10m}"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --limit-rate=*) LIMIT_RATE="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--workdir=<path>] [--limit-rate=10m]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd wget md5sum jq
require_region "${REGION}"

pbf_url="$(region_pbf_url "${REGION}")"
md5_url="$(region_md5_url "${REGION}")"
basename="$(region_pbf_basename "${REGION}")"
[[ -n "${pbf_url}" && -n "${md5_url}" && -n "${basename}" ]] \
  || die "${HUAVD_EXIT_INPUT}" "region lacks Geofabrik pbf/md5 settings: ${REGION}"

mirror="$(mirror_dir)"
ensure_dir "${mirror}"

log_info "fetch PBF: ${pbf_url}"
wget --timestamping --limit-rate="${LIMIT_RATE}" -P "${mirror}" "${pbf_url}" \
  || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "failed to download PBF: ${pbf_url}"

log_info "fetch MD5: ${md5_url}"
wget --timestamping -P "${mirror}" "${md5_url}" \
  || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "failed to download MD5: ${md5_url}"

(
  cd -- "${mirror}"
  md5sum -c "${basename}.md5"
) || die "${HUAVD_EXIT_REMOTE_OR_TOOL}" "md5 check failed for ${basename}"

printf '%s/%s\n' "${mirror}" "${basename}"
