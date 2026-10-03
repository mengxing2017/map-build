#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/overview.sh"

OVERVIEW="" FORCE=0
for arg in "$@"; do
  case "${arg}" in
    --overview=*) OVERVIEW="${arg#*=}" ;;
    --yyyymmdd=*) YYYYMMDD="${arg#*=}" ;;
    --workdir=*) WORKDIR="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"
validate_yyyymmdd "${YYYYMMDD}"
require_cmd jq osmium
overview_validate "${OVERVIEW}"

replication_value() {
  local file="$1" key="$2" value
  value="$(osmium fileinfo -e -g "header.option.${key}" "${file}" 2>/dev/null || true)"
  value="${value//$'\n'/}"
  [[ -n "${value}" && "${value}" != "(none)" && "${value}" != "n/a" ]] || return 1
  printf '%s\n' "${value}"
}

declare -a fingerprints=() inputs=() timestamps=() sequences=()
while IFS= read -r region; do
  basename="$(region_pbf_basename "${region}")"
  input="$(mirror_dir)/${basename}"
  md5_file="${input}.md5"
  require_file "${input}"
  require_file "${md5_file}"
  expected_md5="$(awk '{print $1; exit}' "${md5_file}")"
  actual_md5="$(md5_value "${input}")"
  [[ -n "${expected_md5}" && "${expected_md5}" == "${actual_md5}" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "mirror MD5 mismatch for ${region}: refetch the PBF and its .md5 sidecar"
  timestamp="$(replication_value "${input}" osmosis_replication_timestamp || true)"
  sequence="$(replication_value "${input}" osmosis_replication_sequence_number || true)"
  [[ -n "${timestamp}" ]] \
    || die "${HUAVD_EXIT_INPUT}" "missing replication timestamp for ${region}; fetch a verified same-snapshot input set"
  inputs+=("${input}") timestamps+=("${timestamp}") sequences+=("${sequence}")
  fingerprints+=("$(jq -n --arg region "${region}" --arg basename "${basename}" --arg sha512 "$(sha512_value "${input}")" --arg timestamp "${timestamp}" --arg sequence "${sequence}" --arg url "$(region_pbf_url "${region}")" --arg md5 "${actual_md5}" '{region:$region,basename:$basename,url:$url,md5:$md5,sha512:$sha512,replication:{timestamp:$timestamp,sequence:$sequence}}')")
done < <(overview_source_regions "${OVERVIEW}")

for i in "${!timestamps[@]}"; do
  if [[ "${timestamps[$i]}" != "${timestamps[0]}" ]]; then
    printf 'snapshot mismatch for overview=%s:\n' "${OVERVIEW}" >&2
    for j in "${!inputs[@]}"; do printf '  %s timestamp=%s sequence=%s\n' "${inputs[$j]}" "${timestamps[$j]}" "${sequences[$j]}" >&2; done
    die "${HUAVD_EXIT_INPUT}" "source PBFs must share one replication timestamp; refetch a consistent batch"
  fi
done

fingerprint_json="$(printf '%s\n' "${fingerprints[@]}" | jq -s --arg overview "${OVERVIEW}" --argjson schema "$(jq -r '.schema_version' "$(overviews_json)")" '{overview:$overview,schema_version:$schema,inputs:sort_by(.region)}')"
fingerprint="$(printf '%s' "${fingerprint_json}" | sha512_stdin)"
cache_dir="$(overview_merge_cache_dir "${OVERVIEW}")"
cache_path="${cache_dir}/${fingerprint}.osm.pbf"
lineage_path="${cache_dir}/${fingerprint}.json"
ensure_dir "${cache_dir}"

validate_merged() {
  local file="$1" ordered versions
  ordered="$(osmium fileinfo -e -g data.objects_ordered "${file}" 2>/dev/null || true)"
  versions="$(osmium fileinfo -e -g data.multiple_versions "${file}" 2>/dev/null || true)"
  [[ "${ordered}" == "yes" && "${versions}" == "no" ]] \
    || die "${HUAVD_EXIT_VERIFY}" "merged PBF failed ordered/no-multiple-versions check: ordered=${ordered:-missing} multiple_versions=${versions:-missing}"
}

if [[ "${FORCE}" == 1 || ! -f "${cache_path}" ]]; then
  tmp="${cache_path}.tmp.$$"
  rm -f "${tmp}"
  log_info "osmium merge overview=${OVERVIEW} fingerprint=${fingerprint}"
  osmium merge -O -o "${tmp}" "${inputs[@]}" || die "${HUAVD_EXIT_ERROR}" "osmium merge failed"
  validate_merged "${tmp}"
  mv "${tmp}" "${cache_path}"
  printf '%s\n' "${fingerprint_json}" > "${lineage_path}"
else
  validate_merged "${cache_path}"
fi
printf '%s\n' "${cache_path}"
