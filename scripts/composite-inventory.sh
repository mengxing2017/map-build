#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/composite.sh"

COMPOSITE=""
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --composite=*) COMPOSITE="${arg#*=}" ;;
    -h|--help) printf 'usage: %s --composite=<id> [--workdir=<path>]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

[[ -n "${COMPOSITE}" ]] || die "${HUAVD_EXIT_INPUT}" "--composite is required"
require_cmd jq osmium md5sum
composite_validate "${COMPOSITE}"

failures=0
timestamps=()
sequences=()
while IFS= read -r region; do
  basename="$(composite_pbf_basename "${COMPOSITE}" "${region}")"
  pbf="$(mirror_dir)/${basename}"
  sidecar="${pbf}.md5"
  if [[ ! -f "${pbf}" ]]; then
    printf 'MISSING region=%s pbf=%s\n' "${region}" "${pbf}"
    failures=$((failures + 1))
    continue
  fi
  if [[ ! -f "${sidecar}" ]]; then
    printf 'MISSING region=%s md5=%s\n' "${region}" "${sidecar}"
    failures=$((failures + 1))
    continue
  fi
  expected="$(awk '{print $1; exit}' "${sidecar}")"
  actual="$(md5sum "${pbf}" | awk '{print $1}')"
  if [[ -z "${expected}" || "${expected}" != "${actual}" ]]; then
    printf 'INVALID region=%s md5 expected=%s actual=%s\n' "${region}" "${expected:-missing}" "${actual}"
    failures=$((failures + 1))
    continue
  fi
  timestamp="$(osmium fileinfo -e -g header.option.osmosis_replication_timestamp "${pbf}" 2>/dev/null || true)"
  sequence="$(osmium fileinfo -e -g header.option.osmosis_replication_sequence_number "${pbf}" 2>/dev/null || true)"
  timestamp="${timestamp//$'\n'/}"
  sequence="${sequence//$'\n'/}"
  if [[ -z "${timestamp}" || "${timestamp}" == "(none)" || "${timestamp}" == "n/a" || -z "${sequence}" || "${sequence}" == "(none)" || "${sequence}" == "n/a" ]]; then
    printf 'INVALID region=%s replication=missing pbf=%s\n' "${region}" "${pbf}"
    failures=$((failures + 1))
    continue
  fi
  timestamps+=("${timestamp}")
  sequences+=("${sequence}")
  printf 'READY region=%s pbf=%s timestamp=%s sequence=%s\n' "${region}" "${pbf}" "${timestamp}" "${sequence}"
done < <(composite_source_regions "${COMPOSITE}")

if (( failures == 0 )); then
  for index in "${!timestamps[@]}"; do
    if [[ "${timestamps[$index]}" != "${timestamps[0]}" || "${sequences[$index]}" != "${sequences[0]}" ]]; then
      printf 'MISMATCH region=%s timestamp=%s sequence=%s expected_timestamp=%s expected_sequence=%s\n' \
        "$(composite_source_regions "${COMPOSITE}" | sed -n "$((index + 1))p")" "${timestamps[$index]}" "${sequences[$index]}" "${timestamps[0]}" "${sequences[0]}"
      failures=$((failures + 1))
    fi
  done
fi

(( failures == 0 )) || die "${HUAVD_EXIT_INPUT}" "composite inventory failed: ${COMPOSITE} (${failures} issue(s))"
printf 'composite-inventory: PASS composite=%s sources=%s\n' "${COMPOSITE}" "${#timestamps[@]}"
