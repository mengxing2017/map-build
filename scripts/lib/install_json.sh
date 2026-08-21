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
if [[ -z "${HUAVD_MAP_BUILD_VIEWPORT_LOADED:-}" ]]; then
  # shellcheck source=viewport.sh
  source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/viewport.sh"
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

viewport_for_offline_map() {
  local role="$1"
  local pmtiles="$2"

  if [[ "${role}" == "building" ]]; then
    pmtiles="$(build_pmtiles_path base)"
  fi

  if [[ ! -f "${pmtiles}" ]]; then
    log_warn "no pmtiles for viewport: ${pmtiles}"
    printf '%s' '{}'
    return 0
  fi

  local center_lng center_lat _ default_zoom
  read -r center_lng center_lat _ < <(viewport_extract_center "${pmtiles}")
  default_zoom="$(viewport_calc_default_zoom "${pmtiles}")"

  jq -n \
    --argjson center "[${center_lng}, ${center_lat}]" \
    --argjson default_zoom "${default_zoom}" \
    '{center: $center, default_zoom: $default_zoom}'
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
  local fallback_package_version
  fallback_package_version="$(region_package_version "${REGION}" "${role}")"
  fallback_package_version="${fallback_package_version:-${YYYYMMDD}.${role}}"

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
    --arg fallback_glyphs_url "$(glyphs_url_template)" \
    --arg fallback_styles_url "$(if [[ "${role}" == "raster_bake" ]]; then raster_styles_url; else styles_url; fi)" \
    --arg fallback_package_version "${fallback_package_version}" \
    --arg role "${role}" \
    --arg sha512 "${file_sha}" \
    --arg file "${stem}.pmtiles" \
    --argjson viewport "$(viewport_for_offline_map "${role}" "${pmtiles}")" \
    '
      def install_tile_range($range):
        if $range == null then
          null
        else
          {
            "min-zoom": $range.min_zoom,
            "max-zoom": $range.max_zoom,
            bounds: $range.bounds
          }
        end;

      ($manifest[0]) as $m
      | ($m.huavd_record // {}) as $h
      | {
          id: (($h.id // "") | if . == "" then $fallback_id else . end),
          name: (($h.name // "") | if . == "" then $fallback_name else . end),
          "source-id": (($h.source_id // "") | if . == "" then $fallback_source_id else . end),
          "package-version": (($h.package_version // "") | if . == "" then $fallback_package_version else . end),
          "source-revision": ($h.source_revision // null),
          "asset-role": (($h.asset_role // "") | if . == "" then $fallback_asset_role else . end),
          "source-type": (($h.source_type // "") | if . == "" then $fallback_source_type else . end),
          format: (($h.format // "") | if . == "" then $fallback_format else . end),
          "coord-system": (($h.coord_system // "") | if . == "" then $fallback_coord_system else . end),
          transport: (($h.transport // "") | if . == "" then $fallback_transport else . end),
          "style-id": (($h.style_id // "") | if . == "" then $fallback_style_id else . end),
          "available-locales": (($h.available_locales // []) | if type == "array" then . else [] end),
          "style-locales": (($h.style_locales // []) | if type == "array" then . else [] end),
          "glyphs-url": (($h.glyphs_url // "") | if . == "" then $fallback_glyphs_url else . end),
          "styles-url": (($h.styles_url // "") | if . == "" then $fallback_styles_url else . end),
          "coverage-region-id": (($m.region // "") | if . == "" then null else . end),
          "tile-range": install_tile_range($m.output.tile_range // null),
          checksum: {
            algorithm: "sha512",
            value: $sha512
          },
          file: $file,
          "released-at": (($h.released_at // $m.build_id // "") | if . == "" then $fallback_released_at else . end),
          viewport: $viewport
        }
        + (if ($h.dem_encoding // "") == "" then {} else {"dem-encoding": $h.dem_encoding} end)
    ' | jq -e --arg role "${role}" '
      if (.id == "" or .name == "" or ."source-id" == "" or ."package-version" == "" or ."asset-role" == "" or ."coord-system" == "" or ."style-id" == "") then
        error("required install.json offline-map field is empty")
      elif has("url") then
        error("install.json offline-map must not include url")
      elif (.name | endswith(".pmtiles")) then
        error("install.json offline-map name must not include .pmtiles")
      elif (."coord-system" != "EPSG:3857") then
        error("install.json coord-system must be EPSG:3857")
      elif ($role == "dem" and (."source-type" != "dem" or ."asset-role" != "dem-raster" or (."dem-encoding" // "") == "")) then
	        error("install.json DEM entry must use source-type=dem, asset-role=dem-raster and dem-encoding")
	      elif ($role == "raster_bake" and (."source-type" != "osm-raster-baked" or ."asset-role" != "raster-baked")) then
	        error("install.json raster_bake entry must use source-type=osm-raster-baked and asset-role=raster-baked")
	      elif (($role != "dem" and $role != "raster_bake") and ."source-type" != "osm-pbf") then
	        error("install.json vector source-type must be osm-pbf")
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

install_offline_maps_require_glyphs() {
  local offline_maps_json="$1"
  jq -e '
    any(.[]; ((."glyphs-url" // "") | startswith("huavd-map://glyphs/")))
  ' >/dev/null <<< "${offline_maps_json}"
}

install_offline_maps_require_styles() {
  local offline_maps_json="$1"
  jq -e '
    any(.[]; ((."styles-url" // "") | startswith("huavd-map://styles/")))
  ' >/dev/null <<< "${offline_maps_json}"
}

install_package_has_glyphs() {
  local package_dir="$1"
  [[ -d "${package_dir}/glyphs" ]] \
    && [[ -n "$(find "${package_dir}/glyphs" -type f -name '*.pbf' -print -quit)" ]]
}

install_package_has_style() {
  local package_dir="$1"
  [[ -d "${package_dir}/styles" ]] \
    && [[ -n "$(find "${package_dir}/styles" -type f -name '*.style.json' -print -quit)" ]]
}

install_package_has_sprite() {
  local package_dir="$1"
  [[ -f "${package_dir}/sprite/sprite.json" ]] && [[ -f "${package_dir}/sprite/sprite.png" ]]
}

install_package_style_requires_sprite() {
  local package_dir="$1"
  local style_file
  style_file="$(find "${package_dir}/styles" -type f -name '*.style.json' -print -quit 2>/dev/null || true)"
  [[ -n "${style_file}" ]] || return 1
  jq -e '(.sprite // "") | startswith("huavd-map://sprite/")' "${style_file}" >/dev/null
}

install_require_declared_assets() {
  local package_dir="$1"
  local offline_maps_json="$2"

  if install_offline_maps_require_glyphs "${offline_maps_json}" && ! install_package_has_glyphs "${package_dir}"; then
    die "${HUAVD_EXIT_INPUT}" "install.json declares huavd-map glyphs-url, but package is missing glyphs/*.pbf; run glyph generation before packaging"
  fi
  if install_offline_maps_require_styles "${offline_maps_json}" && ! install_package_has_style "${package_dir}"; then
    die "${HUAVD_EXIT_INPUT}" "install.json declares huavd-map styles-url, but package is missing styles/*.style.json; run style generation before packaging"
  fi
  if install_package_style_requires_sprite "${package_dir}" && ! install_package_has_sprite "${package_dir}"; then
    die "${HUAVD_EXIT_INPUT}" "style.json declares huavd-map sprite, but package is missing sprite/sprite.json and sprite/sprite.png; run sprite generation before packaging"
  fi
}

install_outputs_have_glyphs() {
  local glyphs_dir
  glyphs_dir="$(build_glyphs_dir)"
  [[ -d "${glyphs_dir}" ]] && [[ -n "$(find "${glyphs_dir}" -type f -name '*.pbf' -print -quit)" ]]
}

install_outputs_have_style() {
  [[ -f "$(build_style_path)" ]]
}

install_outputs_have_sprite() {
  local sprite_dir
  sprite_dir="$(build_sprite_dir)"
  [[ -f "${sprite_dir}/sprite.json" ]] && [[ -f "${sprite_dir}/sprite.png" ]]
}

install_output_style_requires_sprite() {
  local style_file
  style_file="$(build_style_path)"
  [[ -f "${style_file}" ]] || return 1
  jq -e '(.sprite // "") | startswith("huavd-map://sprite/")' "${style_file}" >/dev/null
}

install_ensure_declared_outputs() {
  local offline_maps_json="$1"

  if install_offline_maps_require_glyphs "${offline_maps_json}" && ! install_outputs_have_glyphs; then
    log_info "glyph output missing; generating glyphs before packaging"
    "${SCRIPT_DIR}/glyph.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --workdir="${WORKDIR}" --force
  fi
  if install_offline_maps_require_styles "${offline_maps_json}" && ! install_outputs_have_style; then
    log_info "style output missing; generating style before packaging"
    "${SCRIPT_DIR}/style.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --workdir="${WORKDIR}"
  fi
  if install_outputs_have_style && install_output_style_requires_sprite && ! install_outputs_have_sprite; then
    log_info "sprite output missing; generating sprite before packaging"
    "${SCRIPT_DIR}/sprite.sh" --region="${REGION}" --yyyymmdd="${YYYYMMDD}" --session="${SESSION}" --workdir="${WORKDIR}" --force
  fi
}

install_region_is_descendant() {
  local region="$1"
  local root="$2"
  local current parent
  current="${region}"
  while [[ -n "${current}" && "${current}" != "null" ]]; do
    [[ "${current}" == "${root}" ]] && return 0
    parent="$(region_get geofabrik.parent_region "${current}" || true)"
    current="${parent}"
  done
  return 1
}

install_manifest_record_json() {
  local manifest="$1"
  local strict="${2:-1}"
  local output_path pmtiles sha_file manifest_sha file_sha stem region stable_region_id

  if ! command -v jq >/dev/null 2>&1; then
    install_skip_or_die "${strict}" "jq is required to generate aggregate install.json"
    return 1
  fi

  [[ -f "${manifest}" ]] || {
    install_skip_or_die "${strict}" "manifest missing for aggregate install.json: ${manifest}"
    return 1
  }

  output_path="$(jq -r '.output.path // empty' "${manifest}")"
  stem="$(basename -- "${output_path}")"
  stem="${stem%.pmtiles}"
  pmtiles="$(outputs_dir)/$(basename -- "${output_path}")"
  sha_file="${pmtiles}.sha512"
  region="$(jq -r '.region // empty' "${manifest}")"
  stable_region_id="$(region_stable_id "${region}" || true)"
  stable_region_id="${stable_region_id:-${region}}"

  [[ -f "${pmtiles}" ]] || {
    install_skip_or_die "${strict}" "PMTiles missing for aggregate install.json manifest=${manifest}: ${pmtiles}"
    return 1
  }
  [[ -f "${sha_file}" ]] || {
    install_skip_or_die "${strict}" "sha512 sidecar missing for aggregate install.json manifest=${manifest}: ${sha_file}"
    return 1
  }

  manifest_sha="$(jq -r '.output.sha512 // empty' "${manifest}")"
  if [[ -z "${manifest_sha}" || "${manifest_sha}" == "null" ]]; then
    install_skip_or_die "${strict}" "manifest output.sha512 missing for aggregate install.json: ${manifest}"
    return 1
  fi
  file_sha="$(awk '{print $1; exit}' "${sha_file}")"
  if [[ "${file_sha}" != "${manifest_sha}" ]]; then
    install_skip_or_die "${strict}" "sha512 sidecar does not match aggregate manifest: ${sha_file}"
    return 1
  fi

  local manifest_role
  manifest_role="$(jq -r '.huavd_record.asset_role // empty' "${manifest}")"
  local fallback_package_version
  case "${manifest_role}" in
    building-vector) fallback_package_version="$(region_package_version "${region}" building)" ;;
    dem-raster) fallback_package_version="$(region_package_version "${region}" dem)" ;;
    *) fallback_package_version="$(region_package_version "${region}" base)" ;;
  esac
  fallback_package_version="${fallback_package_version:-${YYYYMMDD}.${role:-base}}"

  jq -n \
    --slurpfile manifest "${manifest}" \
    --arg fallback_released_at "$(timestamp_utc)" \
    --arg stable_region_id "${stable_region_id}" \
    --arg sha512 "${file_sha}" \
    --arg file "$(basename -- "${pmtiles}")" \
    --arg fallback_name "${stem}" \
    --arg fallback_package_version "${fallback_package_version}" \
    '
      def install_tile_range($range):
        if $range == null then
          null
        else
          {
            "min-zoom": $range.min_zoom,
            "max-zoom": $range.max_zoom,
            bounds: $range.bounds
          }
        end;

      ($manifest[0]) as $m
      | ($m.huavd_record // {}) as $h
      | {
          id: (($h.id // "") | if . == "" then ($file | sub("\\.pmtiles$"; "")) else . end),
          name: (($h.name // "") | if . == "" then $fallback_name else . end),
          "source-id": ($h.source_id // ""),
          "package-version": (($h.package_version // "") | if . == "" then $fallback_package_version else . end),
          "source-revision": ($h.source_revision // null),
          "asset-role": ($h.asset_role // ""),
          "source-type": ($h.source_type // ""),
          format: (($h.format // "") | if . == "" then "pmtiles" else . end),
          "coord-system": (($h.coord_system // "") | if . == "" then "EPSG:3857" else . end),
          transport: (($h.transport // "") | if . == "" then "offline" else . end),
          "style-id": (($h.style_id // "") | if . == "" then "osm-dev" else . end),
          "available-locales": (($h.available_locales // []) | if type == "array" then . else [] end),
          "style-locales": (($h.style_locales // []) | if type == "array" then . else [] end),
          "coverage-region-id": $stable_region_id,
          "tile-range": install_tile_range($m.output.tile_range // null),
          checksum: {
            algorithm: "sha512",
            value: $sha512
          },
          file: $file,
          "released-at": (($h.released_at // $m.build_id // "") | if . == "" then $fallback_released_at else . end)
        }
        + (if ($h.dem_encoding // "") == "" then {} else {"dem-encoding": $h.dem_encoding} end)
    ' | jq -e '
      if (.id == "" or .name == "" or ."source-id" == "" or ."package-version" == "" or ."asset-role" == "" or ."coord-system" == "" or ."style-id" == "") then
        error("required aggregate install.json offline-map field is empty")
      elif (."asset-role" != "base-vector") then
        error("aggregate install.json currently accepts base-vector manifests only")
      elif (."coord-system" != "EPSG:3857") then
        error("aggregate install.json coord-system must be EPSG:3857")
      else
        .
      end
    ' || {
      install_skip_or_die "${strict}" "failed to build aggregate install.json offline-map entry: ${manifest}"
      return 1
    }
}

install_aggregate_offline_maps_json() {
  local strict="$1"
  local root_region="$2"
  local tmp manifest region role count
  tmp="$(mktemp)"
  count=0
  while IFS= read -r manifest; do
    region="$(jq -r '.region // empty' "${manifest}")"
    role="$(jq -r '.huavd_record.asset_role // empty' "${manifest}")"
    [[ "${role}" == "base-vector" ]] || continue
    install_region_is_descendant "${region}" "${root_region}" || continue
    if install_manifest_record_json "${manifest}" "${strict}" >> "${tmp}"; then
      count=$((count + 1))
    fi
  done < <(find "$(outputs_dir)" -maxdepth 1 -type f -name '*.base.manifest.json' | sort)

  if (( count == 0 )); then
    rm -f "${tmp}"
    install_skip_or_die "${strict}" "no base-vector manifests found for aggregate root region=${root_region}"
    return 1
  fi
  jq -s 'sort_by(."coverage-region-id", id)' "${tmp}"
  rm -f "${tmp}"
}

install_write_document() {
  local output="$1"
  local transfer_id="$2"
  local offline_maps_json="$3"
  local document_region="$4"
  local bundle_id="$5"
  local activation="$6"
  install_write_document_impl "${output}" "${transfer_id}" "${offline_maps_json}" "${document_region}" "${bundle_id}" "${activation}" "0"
}

install_write_aggregate_document() {
  local output="$1"
  local transfer_id="$2"
  local offline_maps_json="$3"
  local document_region="$4"
  local bundle_id="$5"
  local activation="$6"
  install_write_document_impl "${output}" "${transfer_id}" "${offline_maps_json}" "${document_region}" "${bundle_id}" "${activation}" "1"
}

install_write_document_impl() {
  local output="$1"
  local transfer_id="$2"
  local offline_maps_json="$3"
  local document_region="$4"
  local bundle_id="$5"
  local activation="$6"
  local aggregate="$7"
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
    --arg aggregate "${aggregate}" \
    --argjson offline_maps "${offline_maps_json}" \
    '
      def region_id($map):
        (($map."coverage-region-id" // "") | if . == "" or . == null then "" else . end);

      def coverage_bounds($maps):
        ($maps | map(."tile-range".bounds? // empty)) as $bounds
        | if ($bounds | length) == 0 then
            [-180, -90, 180, 90]
          else
            [
              ($bounds | map(.[0]) | min),
              ($bounds | map(.[1]) | min),
              ($bounds | map(.[2]) | max),
              ($bounds | map(.[3]) | max)
            ]
          end;

      def coverage_region_ids($maps; $aggregate):
        if $aggregate == "1" then
          ($maps
            | map(select(."asset-role" == "base-vector"))
            | map(region_id(.))
            | map(select(. != ""))
            | unique)
        else
          []
        end;

      def presentation_scope($role):
        if $role == "raster-baked" then
          ["standard", "standard-buildings"]
        elif $role == "dem-raster" then
          ["terrain-3d", "terrain-3d-buildings", "satellite-3d", "city-3d"]
        elif $role == "building-vector" then
          ["standard-buildings", "terrain-3d-buildings", "city-3d"]
        else
          ["standard", "standard-buildings", "terrain-3d", "terrain-3d-buildings"]
        end;

	      def asset_required($role):
	        if $role == "base-vector" or $role == "raster-baked" then true else false end;

      def asset_record($entry; $required; $order; $include_region):
        {
          "offline-map-id": $entry.value.id,
          "asset-role": $entry.value."asset-role",
          required: $required,
          "presentation-scope": presentation_scope($entry.value."asset-role"),
          order: $order
        }
        + (if ($include_region == "1" and region_id($entry.value) != "") then {"coverage-region-id": region_id($entry.value)} else {} end);

      def bundle_assets($maps; $aggregate):
        ($maps | map(select(."asset-role" == "base-vector")) | .[0]) as $base
        | ($maps | map(select(."asset-role" == "base-vector"))) as $bases
	        | ($maps | map(select(."asset-role" == "raster-baked"))) as $rasters
	        | ($maps | map(select(."asset-role" == "building-vector"))) as $buildings
	        | ($maps | map(select(."asset-role" == "dem-raster"))) as $dems
        | if $base == null then
            []
          elif $aggregate == "1" then
	            (($rasters | to_entries | map(asset_record(.; true; (10 + .key); "1")))
	             + ($bases | to_entries | map(asset_record(.; true; (20 + .key); "1")))
	             + ($buildings | to_entries | map(asset_record(.; false; (30 + .key); "1")))
	             + ($dems | to_entries | map(asset_record(.; false; (40 + .key); "1"))))
	          else
	            (
	              ($rasters | to_entries | map(asset_record(.; true; (10 + .key); "0")))
	              + [({key: 0, value: $base} | asset_record(.; true; 20; "0"))]
	              + ($buildings | to_entries | map(asset_record(.; false; (30 + .key); "0")))
	              + ($dems | to_entries | map(asset_record(.; false; (40 + .key); "0")))
	            )
          end;

      def bundles($maps; $aggregate):
        ($maps | map(select(."asset-role" == "base-vector")) | .[0]) as $base
        | ($maps | any(."asset-role" == "dem-raster")) as $has_dem
        | ($maps | any(."asset-role" == "building-vector")) as $has_building
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
                "supported-presentations": (
                  ["standard"]
                  + (if $has_building then ["standard-buildings"] else [] end)
                  + (if $has_dem then ["terrain-3d"] else [] end)
                  + (if ($has_dem and $has_building) then ["terrain-3d-buildings", "city-3d"] else [] end)
                ),
                "default-presentation": "standard",
                "style-locales": ($base."style-locales" // []),
                "coverage-bounds": coverage_bounds($maps),
                "coverage-region-ids": coverage_region_ids($maps; $aggregate),
                "license-status": "not-required",
                activation: $activation,
                assets: bundle_assets($maps; $aggregate)
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
        bundles: bundles($offline_maps; $aggregate)
      }
    ' > "${output}"
}
