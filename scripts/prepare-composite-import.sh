#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; source "${SCRIPT_DIR}/lib/common.sh"; source "${SCRIPT_DIR}/lib/config.sh"; source "${SCRIPT_DIR}/lib/composite.sh"
COMPOSITE="" FORMAT="${IMPORT_FORMAT:-zip}" passthrough=()
for arg in "$@"; do if parse_common_arg "${arg}"; then continue; fi; case "${arg}" in --composite=*) COMPOSITE="${arg#*=}";; --format=*) FORMAT="${arg#*=}";; --output=*|--transfer-id=*) passthrough+=("${arg}");; -h|--help) printf 'usage: %s --composite=<id> [--yyyymmdd=YYYYMMDD] [--session=<session>] [--format=tar|zip] [--output=<archive-path>] [--transfer-id=<id>] [--workdir=<path>]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${COMPOSITE}" ]] || die "${HUAVD_EXIT_INPUT}" "--composite is required"; composite_validate "${COMPOSITE}"; REGION="$(composite_target_region "${COMPOSITE}")"; normalize_session_vars
"${SCRIPT_DIR}/verify-composite.sh" --composite="${COMPOSITE}" --session="${SESSION}" --workdir="${WORKDIR}" --strict
"${SCRIPT_DIR}/prepare-import.sh" --region="${REGION}" --session="${SESSION}" --role=base --format="${FORMAT}" --workdir="${WORKDIR}" "${passthrough[@]}"
