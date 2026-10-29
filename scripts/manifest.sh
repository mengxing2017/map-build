#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --allow-missing-source) ALLOW_MISSING_SOURCE=1 ;;
    -h|--help)
      printf 'usage: %s --region=<id> --role=<base|building|raster_bake> [--workdir=<path>] [--yyyymmdd=YYYYMMDD] [--allow-missing-source]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

case "${ROLE}" in
  base|building)
    normalize_session_vars
    python="$(huavd_python)"
    args=(artifact write-vector-manifest --region="${REGION}"
      --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --role="${ROLE}"
      --workdir="${WORKDIR}" --activation="${HUAVD_MAP_ACTIVATION:-manual}")
    [[ -n "${HUAVD_MAP_BUNDLE_ID:-}" ]] \
      && args+=(--bundle-id="${HUAVD_MAP_BUNDLE_ID}")
    [[ "${ALLOW_MISSING_SOURCE:-0}" == 1 ]] \
      && args+=(--allow-missing-source)
    PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
      exec "${python}" -m huavd_map_build "${args[@]}"
    ;;
  raster_bake)
    require_cmd jq
    require_region "${REGION}"
    normalize_session_vars
    pmtiles="$(build_pmtiles_path raster_bake)"
    manifest="$(build_manifest_path raster_bake)"
    require_file "${pmtiles}"
    base_pmtiles="$(build_pmtiles_path base)"
    base_manifest="$(build_manifest_path base)"
    require_file "${base_pmtiles}"
    require_file "${base_manifest}"
    bake_parameters="$(bake_cache_dir)/parameters.json"
    require_file "${bake_parameters}"
    raster_tile_size="$(jq -r '.effective.tile_size // empty' "${bake_parameters}")"
    [[ "${raster_tile_size}" =~ ^[1-9][0-9]*$ ]] \
      || die "${HUAVD_EXIT_VERIFY}" "raster_bake parameters have no valid tile_size"
    raster_tile_count="$(pmtiles_addressed_tiles_count "${pmtiles}")"
    [[ "${raster_tile_count}" =~ ^[1-9][0-9]*$ ]] \
      || die "${HUAVD_EXIT_VERIFY}" "raster_bake PMTiles has no addressed tiles"
    python="$(huavd_python)"
    args=(artifact write-raster-manifest --region="${REGION}"
      --yyyymmdd="${YYYYMMDD}" --session="${SESSION}"
      --workdir="${WORKDIR}" --pmtiles="${pmtiles}" --manifest="${manifest}"
      --tile-count="${raster_tile_count}" --tile-size="${raster_tile_size}"
      --activation="${HUAVD_MAP_ACTIVATION:-manual}")
    [[ -n "${HUAVD_MAP_BUNDLE_ID:-}" ]] \
      && args+=(--bundle-id="${HUAVD_MAP_BUNDLE_ID}")
    PYTHONPATH="${REPO_ROOT}/backend/src${PYTHONPATH:+:${PYTHONPATH}}" \
      exec "${python}" -m huavd_map_build "${args[@]}"
    ;;
  *)
    die "${HUAVD_EXIT_INPUT}" "manifest role must be base, building, or raster_bake"
    ;;
esac
