#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/config.sh"
source "${SCRIPT_DIR}/lib/source-asset.sh"

ASSET=""
for arg in "$@"; do
  if parse_common_arg "${arg}"; then continue; fi
  case "${arg}" in
    --asset=*) ASSET="${arg#*=}" ;;
    -h|--help) printf 'usage: %s --asset=<id> [--workdir=<path>]\n' "$0"; exit 0 ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done
[[ -n "${ASSET}" ]] || die "${HUAVD_EXIT_INPUT}" "--asset is required"
require_cmd jq
source_asset_validate "${ASSET}"

failures=0
while IFS= read -r region; do
  input="$(source_asset_input_path "${ASSET}" "${region}")"
  sidecar="${input}.md5"
  if [[ ! -f "${input}" ]]; then
    printf 'MISSING asset=%s region=%s input=%s\n' "${ASSET}" "${region}" "${input}"
    failures=$((failures + 1)); continue
  fi
  if [[ ! -f "${sidecar}" ]]; then
    printf 'MISSING asset=%s region=%s md5=%s\n' "${ASSET}" "${region}" "${sidecar}"
    failures=$((failures + 1)); continue
  fi
  expected="$(awk '{print $1; exit}' "${sidecar}")"
  actual="$(md5_value "${input}")"
  if [[ -z "${expected}" || "${expected}" != "${actual}" ]]; then
    printf 'INVALID asset=%s region=%s md5 expected=%s actual=%s\n' "${ASSET}" "${region}" "${expected:-missing}" "${actual}"
    failures=$((failures + 1)); continue
  fi
  printf 'READY asset=%s region=%s input=%s sha512=%s\n' "${ASSET}" "${region}" "${input}" "$(sha512_value "${input}")"
done < <(source_asset_input_regions "${ASSET}")
(( failures == 0 )) || die "${HUAVD_EXIT_INPUT}" "source inventory failed: ${ASSET} (${failures} issue(s))"
printf 'source-inventory: PASS asset=%s\n' "${ASSET}"
