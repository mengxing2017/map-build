#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_COMMON_LOADED:-}" ]]; then
  # shellcheck source=common.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
fi
HUAVD_MAP_BUILD_PMTILES_LOADED=1

pmtiles_magic() {
  local file="$1"
  dd if="${file}" bs=1 count=7 2>/dev/null
}

pmtiles_byte() {
  local file="$1"
  local offset="$2"
  od -An -tu1 -j "${offset}" -N 1 "${file}" | tr -d '[:space:]'
}

pmtiles_i32() {
  local file="$1"
  local offset="$2"
  od -An -td4 -j "${offset}" -N 4 "${file}" | tr -d '[:space:]'
}

pmtiles_u64() {
  local file="$1"
  local offset="$2"
  od -An -tu8 -j "${offset}" -N 8 "${file}" | tr -d '[:space:]'
}

pmtiles_spec_version() {
  pmtiles_byte "$1" 7
}

pmtiles_root_offset() {
  pmtiles_u64 "$1" 8
}

pmtiles_root_length() {
  pmtiles_u64 "$1" 16
}

pmtiles_internal_compression() {
  pmtiles_byte "$1" 97
}

pmtiles_tile_compression() {
  pmtiles_byte "$1" 98
}

pmtiles_tile_type() {
  pmtiles_byte "$1" 99
}

pmtiles_min_zoom() {
  pmtiles_byte "$1" 100
}

pmtiles_max_zoom() {
  pmtiles_byte "$1" 101
}

pmtiles_bounds() {
  local file="$1"
  local west south east north
  west="$(pmtiles_i32 "${file}" 102)"
  south="$(pmtiles_i32 "${file}" 106)"
  east="$(pmtiles_i32 "${file}" 110)"
  north="$(pmtiles_i32 "${file}" 114)"
  jq -n \
    --argjson west "${west}" \
    --argjson south "${south}" \
    --argjson east "${east}" \
    --argjson north "${north}" \
    '[($west / 10000000), ($south / 10000000), ($east / 10000000), ($north / 10000000)]'
}

pmtiles_center() {
  local file="$1"
  local bounds
  bounds="$(pmtiles_bounds "${file}")"
  jq -c '[((.[0] + .[2]) / 2), ((.[1] + .[3]) / 2), 6]' <<< "${bounds}"
}

pmtiles_header_manifest() {
  local file="$1"
  jq -n \
    --arg magic "$(pmtiles_magic "${file}")" \
    --argjson spec_version "$(pmtiles_spec_version "${file}")" \
    --argjson root_offset "$(pmtiles_root_offset "${file}")" \
    --argjson root_length "$(pmtiles_root_length "${file}")" \
    --argjson internal_compression "$(pmtiles_internal_compression "${file}")" \
    --argjson tile_compression "$(pmtiles_tile_compression "${file}")" \
    --argjson tile_type "$(pmtiles_tile_type "${file}")" \
    --argjson min_zoom "$(pmtiles_min_zoom "${file}")" \
    --argjson max_zoom "$(pmtiles_max_zoom "${file}")" \
    --argjson bounds "$(pmtiles_bounds "${file}")" \
    '{
      magic: $magic,
      spec_version: $spec_version,
      root_offset: $root_offset,
      root_length: $root_length,
      internal_compression: $internal_compression,
      tile_compression: $tile_compression,
      tile_type: $tile_type,
      min_zoom: $min_zoom,
      max_zoom: $max_zoom,
      bounds: $bounds
    }'
}

pmtiles_cli_metadata() {
  local file="$1"
  require_cmd pmtiles
  pmtiles show "${file}" --metadata
}

pmtiles_cli_header_json() {
  local file="$1"
  require_cmd pmtiles
  pmtiles show "${file}" --header-json
}
