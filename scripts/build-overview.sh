#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"; source "${SCRIPT_DIR}/lib/common.sh"; source "${SCRIPT_DIR}/lib/config.sh"; source "${SCRIPT_DIR}/lib/overview.sh"
OVERVIEW="" FORCE=0
for arg in "$@"; do case "${arg}" in --overview=*) OVERVIEW="${arg#*=}";; --yyyymmdd=*) YYYYMMDD="${arg#*=}";; --workdir=*) WORKDIR="${arg#*=}";; --force) FORCE=1;; -h|--help) printf 'usage: %s --overview=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--force]\n' "$0"; exit 0;; *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}";; esac; done
[[ -n "${OVERVIEW}" ]] || die "${HUAVD_EXIT_INPUT}" "--overview is required"; validate_yyyymmdd "${YYYYMMDD}"; require_cmd jq osmium tippecanoe pmtiles; overview_validate "${OVERVIEW}"; ensure_dir "$(outputs_dir)"
pmtiles="$(overview_pmtiles_path "${OVERVIEW}" "${YYYYMMDD}")"; manifest="$(overview_manifest_path "${OVERVIEW}" "${YYYYMMDD}")"; attribution="$(overview_attribution_path "${OVERVIEW}" "${YYYYMMDD}")"; sha="$(overview_sha512_path "${OVERVIEW}" "${YYYYMMDD}")"
if [[ "${FORCE}" != 1 && -f "${pmtiles}" && -f "${manifest}" && -f "${attribution}" && -f "${sha}" ]]; then log_info "overview artifacts already complete: ${OVERVIEW}"; exit 0; fi
merged="$("${SCRIPT_DIR}/merge-pbf.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}" $([[ "${FORCE}" == 1 ]] && printf '%s' --force))"; stage="$(overview_staging_dir "${OVERVIEW}" "${YYYYMMDD}")"; ensure_dir "${stage}"; ln -sfn "${merged}" "${stage}/source.osm.pbf"; basename "${merged}" .osm.pbf > "${stage}/merge-fingerprint"
"${SCRIPT_DIR}/overview-filter.sh" --overview="${OVERVIEW}" --input="${stage}/source.osm.pbf" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/overview-export.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/overview-normalize.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
if overview_layers "${OVERVIEW}" | grep -qx 'admin_line'; then
  "${SCRIPT_DIR}/admin-line-tier.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
fi
"${SCRIPT_DIR}/overview-tippecanoe.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/overview-metadata.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/overview-manifest.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/overview-attribution.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
"${SCRIPT_DIR}/verify-overview.sh" --overview="${OVERVIEW}" --yyyymmdd="${YYYYMMDD}" --workdir="${WORKDIR}"
