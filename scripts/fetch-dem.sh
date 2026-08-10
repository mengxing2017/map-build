#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

SOURCE_ID=""
INPUT=""

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --source=*) SOURCE_ID="${arg#*=}" ;;
    --input=*) INPUT="${arg#*=}" ;;
    -h|--help)
      printf 'usage: %s --region=<id> --session=<session> [--source=<id>] [--input=<path>] [--workdir=<path>]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq
require_region "${REGION}"
normalize_session_vars

SOURCE_ID="${SOURCE_ID:-$(dem_region_source_id "${REGION}")}"
[[ -n "${SOURCE_ID}" ]] || die "${HUAVD_EXIT_INPUT}" "DEM source is not configured"
dem_source_json "${SOURCE_ID}" >/dev/null \
  || die "${HUAVD_EXIT_INPUT}" "DEM source is not configured: ${SOURCE_ID}"

if [[ -z "${INPUT}" ]]; then
  uri="$(dem_source_value "${SOURCE_ID}" uri)"
  case "${uri}" in
    file://*) INPUT="${uri#file://}" ;;
    *)
      die "${HUAVD_EXIT_INPUT}" "DEM source ${SOURCE_ID} requires explicit --input for non-file uri"
      ;;
  esac
fi

INPUT="${INPUT/#\$\{HUAVD_MAP_BUILD_DEM_MIRROR\}/${HUAVD_MAP_BUILD_DEM_MIRROR:-}}"
[[ -n "${INPUT}" ]] || die "${HUAVD_EXIT_INPUT}" "DEM input path is empty"
INPUT="$(resolve_workspace_path "${INPUT}")"

staging_dem_dir="$(staging_dir)/dem/source"
ensure_dir "${staging_dem_dir}"

if [[ -f "${INPUT}" ]]; then
  cp "${INPUT}" "${staging_dem_dir}/$(basename -- "${INPUT}")"
elif [[ -d "${INPUT}" ]]; then
  rm -rf "${staging_dem_dir:?}/"*
  cp -R "${INPUT}/." "${staging_dem_dir}/"
else
  die "${HUAVD_EXIT_INPUT}" "DEM input does not exist: ${INPUT}"
fi

jq -n \
  --arg source_id "${SOURCE_ID}" \
  --arg input "${INPUT}" \
  --arg region "${REGION}" \
  --arg session "${SESSION}" \
  --arg fetched_at "$(timestamp_utc)" \
  '{source_id:$source_id,input:$input,region:$region,session:$session,fetched_at:$fetched_at}' \
  > "$(staging_dir)/dem/source.manifest.json"

if [[ -f "${INPUT}" ]]; then
  write_sha512_file "${staging_dem_dir}/$(basename -- "${INPUT}")"
fi

log_info "DEM source staged: ${staging_dem_dir}"
