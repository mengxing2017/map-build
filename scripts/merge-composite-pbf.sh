#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/composite.sh"

COMPOSITE="" FORCE=0
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --composite=*) COMPOSITE="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help) printf 'usage: %s --composite=<id> [--workdir=<path>] [--force]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

[[ -n "${COMPOSITE}" ]] || die "${HUAVD_EXIT_INPUT}" "--composite is required"
require_cmd jq osmium sha512sum md5sum
composite_validate "${COMPOSITE}"
if ! inventory_output="$("${SCRIPT_DIR}/composite-inventory.sh" --composite="${COMPOSITE}" --workdir="${WORKDIR}" 2>&1)"; then
  printf '%s\n' "${inventory_output}" >&2
  die "${HUAVD_EXIT_INPUT}" "composite inventory failed: ${COMPOSITE}"
fi

declare -a inputs=() fingerprints=()
while IFS= read -r region; do
  basename="$(composite_pbf_basename "${COMPOSITE}" "${region}")"
  pbf="$(mirror_dir)/${basename}"
  md5="$(awk '{print $1; exit}' "${pbf}.md5")"
  timestamp="$(osmium fileinfo -e -g header.option.osmosis_replication_timestamp "${pbf}" | tr -d '\n')"
  sequence="$(osmium fileinfo -e -g header.option.osmosis_replication_sequence_number "${pbf}" | tr -d '\n')"
  inputs+=("${pbf}")
  fingerprints+=("$(jq -n --arg region "${region}" --arg basename "${basename}" --arg md5 "${md5}" --arg sha512 "$(sha512_value "${pbf}")" --arg timestamp "${timestamp}" --arg sequence "${sequence}" '{region:$region,basename:$basename,md5:$md5,sha512:$sha512,replication:{timestamp:$timestamp,sequence:$sequence}}')")
done < <(composite_source_regions "${COMPOSITE}")

lineage="$(printf '%s\n' "${fingerprints[@]}" | jq -s \
  --arg composite "${COMPOSITE}" \
  --arg target_region "$(composite_target_region "${COMPOSITE}")" \
  --argjson composite_schema_version "$(jq -r '.schema_version' "$(composites_json)")" \
  --argjson region_catalog_schema_version "$(jq -r '.schema_version' "$(regions_json)")" \
  --argjson sources "$(composite_source_regions_json "${COMPOSITE}")" \
  --argjson source_config "$(composite_json "${COMPOSITE}" | jq -c '.sources')" \
  --arg provider "$(composite_json "${COMPOSITE}" | jq -r '.inputs.provider')" \
  '{composite:$composite,target_region:$target_region,composite_schema_version:$composite_schema_version,region_catalog_schema_version:$region_catalog_schema_version,provider:$provider,source_config:$source_config,source_regions:$sources,inputs:sort_by(.region)}')"
fingerprint="$(printf '%s' "${lineage}" | sha512sum | awk '{print $1}')"
cache_dir="$(composite_cache_dir "${COMPOSITE}")"
output="${cache_dir}/${fingerprint}.osm.pbf"
ensure_dir "${cache_dir}"
if [[ "${FORCE}" == 1 || ! -f "${output}" ]]; then
  tmp="${output}.tmp.$$"
  rm -f "${tmp}"
  osmium merge -O -o "${tmp}" "${inputs[@]}" || die "${HUAVD_EXIT_ERROR}" "osmium merge failed: ${COMPOSITE}"
  ordered="$(osmium fileinfo -e -g data.objects_ordered "${tmp}" 2>/dev/null || true)"
  versions="$(osmium fileinfo -e -g data.multiple_versions "${tmp}" 2>/dev/null || true)"
  [[ "${ordered}" == yes && "${versions}" == no ]] || die "${HUAVD_EXIT_VERIFY}" "merged PBF invariant failed: ordered=${ordered} multiple_versions=${versions}"
  mv "${tmp}" "${output}"
  printf '%s\n' "${lineage}" > "${cache_dir}/${fingerprint}.json"
fi
printf '%s\n' "${output}"
