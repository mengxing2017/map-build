#!/usr/bin/env bash

set -euo pipefail

if [[ -z "${HUAVD_MAP_BUILD_COMMON_LOADED:-}" ]]; then
  # shellcheck source=common.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
fi
if [[ -z "${HUAVD_MAP_BUILD_CONFIG_LOADED:-}" ]]; then
  # shellcheck source=config.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/config.sh"
fi
HUAVD_MAP_BUILD_INSTALL_JSON_LOADED=1

install_skip_or_die() {
  local strict="$1"
  shift
  if [[ "${strict}" == "1" ]]; then
    die "${HUAVD_EXIT_INPUT}" "$*"
  fi
  log_warn "$*"
  return 1
}

install_transfer_id() {
  if command -v uuidgen >/dev/null 2>&1; then
    uuidgen | tr '[:upper:]' '[:lower:]'
    return
  fi
  printf 'tx-%s-%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$$"
}

install_default_bundle_id() {
  printf '%s-standard\n' "${SESSION}"
}

install_manifest_value_for_roles() {
  local key="$1"
  shift
  local role manifest value
  for role in "$@"; do
    manifest="$(build_manifest_path "${role}")"
    [[ -f "${manifest}" ]] || continue
    value="$(jq -r --arg key "${key}" '.huavd_record[$key] // empty' "${manifest}")"
    if [[ -n "${value}" && "${value}" != "null" ]]; then
      printf '%s\n' "${value}"
      return
    fi
  done
  return 0
}

install_region_for_roles() {
  local role manifest value
  for role in "$@"; do
    manifest="$(build_manifest_path "${role}")"
    [[ -f "${manifest}" ]] || continue
    value="$(jq -r '.region // empty' "${manifest}")"
    if [[ -n "${value}" && "${value}" != "null" ]]; then
      printf '%s\n' "${value}"
      return
    fi
  done
  printf '%s\n' "${REGION}"
}

install_role_record_json() {
  local role="$1"
  local strict="${2:-1}"
  local manifest sha_file pmtiles manifest_sha file_sha stem fallback_id

  if ! command -v jq >/dev/null 2>&1; then
    install_skip_or_die "${strict}" "jq is required to generate install.json"
    return 1
  fi

  manifest="$(build_manifest_path "${role}")"
  sha_file="$(build_sha512_path "${role}")"
  pmtiles="$(build_pmtiles_path "${role}")"
  stem="${SESSION}.${role}"
  fallback_id="${SESSION}-${role}"

  [[ -f "${pmtiles}" ]] || {
    install_skip_or_die "${strict}" "PMTiles missing for install.json role=${role}: ${pmtiles}"
    return 1
  }
  [[ -f "${manifest}" ]] || {
    install_skip_or_die "${strict}" "manifest missing for install.json role=${role}: ${manifest}"
    return 1
  }
  [[ -f "${sha_file}" ]] || {
    install_skip_or_die "${strict}" "sha512 sidecar missing for install.json role=${role}: ${sha_file}"
    return 1
  }

  if ! manifest_sha="$(jq -r '.output.sha512 // empty' "${manifest}")"; then
    install_skip_or_die "${strict}" "manifest is not valid JSON for install.json role=${role}: ${manifest}"
    return 1
  fi
  if [[ -z "${manifest_sha}" || "${manifest_sha}" == "null" ]]; then
    install_skip_or_die "${strict}" "manifest output.sha512 missing for install.json role=${role}: ${manifest}"
    return 1
  fi

  file_sha="$(awk '{print $1; exit}' "${sha_file}")"
  if [[ -z "${file_sha}" ]]; then
    install_skip_or_die "${strict}" "sha512 sidecar is empty for install.json role=${role}: ${sha_file}"
    return 1
  fi
  if [[ "${file_sha}" != "${manifest_sha}" ]]; then
    install_skip_or_die "${strict}" "sha512 sidecar does not match manifest for role=${role}: ${sha_file}"
    return 1
  fi

  jq -n \
    --slurpfile manifest "${manifest}" \
    --arg fallback_id "${fallback_id}" \
    --arg fallback_name "${stem}" \
    --arg fallback_source_id "$(role_source_id "${REGION}" "${role}")" \
    --arg fallback_asset_role "$(role_asset_role "${role}")" \
    --arg fallback_source_type "$(role_source_type "${role}")" \
    --arg fallback_format "pmtiles" \
    --arg fallback_transport "offline" \
    --arg fallback_coord_system "EPSG:3857" \
    --arg fallback_style_id "osm-dev" \
    --arg fallback_released_at "$(timestamp_utc)" \
    --arg sha512 "${file_sha}" \
    --arg file "${stem}.pmtiles" \
    '
      ($manifest[0]) as $m
      | ($m.huavd_record // {}) as $h
      | {
          id: (($h.id // "") | if . == "" then $fallback_id else . end),
          name: (($h.name // "") | if . == "" then $fallback_name else . end),
          "source-id": (($h.source_id // "") | if . == "" then $fallback_source_id else . end),
          "package-version": (($h.package_version // "") | if . == "" then "" else . end),
          "source-revision": ($h.source_revision // null),
          "asset-role": (($h.asset_role // "") | if . == "" then $fallback_asset_role else . end),
          "source-type": (($h.source_type // "") | if . == "" then $fallback_source_type else . end),
          format: (($h.format // "") | if . == "" then $fallback_format else . end),
          "coord-system": (($h.coord_system // "") | if . == "" then $fallback_coord_system else . end),
          transport: (($h.transport // "") | if . == "" then $fallback_transport else . end),
          "style-id": (($h.style_id // "") | if . == "" then $fallback_style_id else . end),
          checksum: {
            algorithm: "sha512",
            value: $sha512
          },
          file: $file,
          "released-at": (($h.released_at // $m.build_id // "") | if . == "" then $fallback_released_at else . end)
        }
    ' | jq -e '
      if (.id == "" or .name == "" or ."source-id" == "" or ."package-version" == "" or ."asset-role" == "" or ."coord-system" == "" or ."style-id" == "") then
        error("required install.json offline-map field is empty")
      elif has("url") then
        error("install.json offline-map must not include url")
      elif (.name | endswith(".pmtiles")) then
        error("install.json offline-map name must not include .pmtiles")
      elif (."coord-system" != "EPSG:3857") then
        error("install.json coord-system must be EPSG:3857")
      elif (."source-type" != "osm-pbf") then
        error("install.json source-type must be osm-pbf")
      else
        .
      end
    ' || {
      install_skip_or_die "${strict}" "failed to build install.json offline-map entry for role=${role}"
      return 1
    }
}

install_offline_maps_json() {
  local strict="$1"
  shift
  local tmp role count
  tmp="$(mktemp)"
  count=0
  for role in "$@"; do
    if install_role_record_json "${role}" "${strict}" >> "${tmp}"; then
      count=$((count + 1))
    fi
  done
  if (( count == 0 )); then
    rm -f "${tmp}"
    install_skip_or_die "${strict}" "no offline_maps entries available for install.json"
    return 1
  fi
  jq -s '.' "${tmp}"
  rm -f "${tmp}"
}

install_write_document() {
  local output="$1"
  local transfer_id="$2"
  local offline_maps_json="$3"
  local document_region="$4"
  local bundle_id="$5"
  local activation="$6"
  local generated_at
  generated_at="$(timestamp_utc)"

  ensure_dir "$(dirname -- "${output}")"
  jq -n \
    --arg schema_version "huavd-map-install/v1" \
    --arg transfer_id "${transfer_id}" \
    --arg session "${SESSION}" \
    --arg region "${document_region}" \
    --arg generated_at "${generated_at}" \
    --arg bundle_id "${bundle_id}" \
    --arg activation "${activation}" \
    --argjson offline_maps "${offline_maps_json}" \
    '
      def bundle_assets($maps):
        ($maps | map(select(."asset-role" == "base-vector")) | .[0]) as $base
        | ($maps | map(select(."asset-role" == "building-vector"))) as $buildings
        | if $base == null then
            []
          else
            (
              [
                {
                  "offline-map-id": $base.id,
                  "asset-role": $base."asset-role",
                  required: true,
                  "presentation-scope": ["standard"],
                  order: 0
                }
              ]
              + ($buildings | to_entries | map({
                  "offline-map-id": .value.id,
                  "asset-role": .value."asset-role",
                  required: false,
                  "presentation-scope": ["standard"],
                  order: (.key + 1)
                }))
            )
          end;

      def bundles($maps):
        ($maps | map(select(."asset-role" == "base-vector")) | .[0]) as $base
        | if $base == null then
            []
          else
            [
              {
                id: $bundle_id,
                name: "Standard Map Bundle",
                "source-id": $base."source-id",
                "bundle-version": $base."package-version",
                "source-revision": ($base."source-revision" // null),
                transport: ($base.transport // "offline"),
                "coord-system": $base."coord-system",
                "supported-presentations": ["standard"],
                "default-presentation": "standard",
                "license-status": "not-required",
                activation: $activation,
                assets: bundle_assets($maps)
              }
            ]
          end;

      {
        schema_version: $schema_version,
        transfer_id: $transfer_id,
        session: $session,
        region: $region,
        generated_at: $generated_at,
        offline_maps: $offline_maps,
        bundles: bundles($offline_maps)
      }
    ' > "${output}"
}
