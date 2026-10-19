#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"
# shellcheck source=lib/source-asset.sh
source "${SCRIPT_DIR}/lib/source-asset.sh"
# shellcheck source=lib/derived-map.sh
source "${SCRIPT_DIR}/lib/derived-map.sh"

REQUIRED=(
  bash
  jq
  wget
  tar
  zip
  osmium
  tippecanoe
  pmtiles
  cwebp
  dwebp
  timeout
  xargs
  node
  pnpm
  fonttools
  build-glyphs
)

WARNINGS=0
FAILURES=0

check_cmd() {
  local cmd="$1"
  local version
  if command -v "${cmd}" >/dev/null 2>&1; then
    version="$(cmd_version "${cmd}")"
    if [[ -n "${version}" && "${version}" != "missing" ]]; then
      printf 'OK   %-12s %s\n' "${cmd}" "${version}"
    elif [[ "${cmd}" == "build-glyphs" ]]; then
      printf 'OK   %-12s found\n' "${cmd}"
    elif [[ "${cmd}" == "fonttools" ]]; then
      printf 'WARN %-12s found but not runnable\n' "${cmd}"
      WARNINGS=$((WARNINGS + 1))
    else
      printf 'WARN %-12s found but not runnable\n' "${cmd}"
      WARNINGS=$((WARNINGS + 1))
    fi
  else
    printf 'WARN %-12s missing\n' "${cmd}"
    WARNINGS=$((WARNINGS + 1))
  fi
}

for cmd in "${REQUIRED[@]}"; do
  check_cmd "${cmd}"
done

check_mbgl_render_cli() {
  local output diagnostic
  if ! command -v mbgl-render >/dev/null 2>&1; then
    printf 'WARN %-12s missing; raster bake default requires npm package mbgl-renderer, or MBGL_RENDER_TILE_COMMAND\n' "mbgl-render"
    WARNINGS=$((WARNINGS + 1))
    return
  fi

  output="$(mbgl-render --help 2>&1 || true)"
  if printf '%s\n' "${output}" | head -n 20 | grep -Eq '(^|[[:space:]])(Usage|usage|Options|--style|--width|--height)'; then
    printf 'OK   %-12s CLI self-test\n' "mbgl-render"
  else
    diagnostic="$(printf '%s\n' "${output}" | awk '/libpng version mismatch/ {sub(/^[[:space:]]*what\(\):[[:space:]]*/, ""); print; found=1; exit} END {if (!found) exit 1}' || true)"
    if [[ -z "${diagnostic}" ]]; then
      diagnostic="$(printf '%s\n' "${output}" | awk 'NF {print; exit}')"
    fi
    printf 'WARN %-12s found but failed CLI self-test%s%s\n' \
      "mbgl-render" \
      "${diagnostic:+: }" \
      "${diagnostic}"
    printf 'hint %-12s run devbox run setup to refresh the project wrapper; libpng version mismatch requires a compatible mbgl-renderer build or MBGL_RENDER_TILE_COMMAND\n' "mbgl-render"
    WARNINGS=$((WARNINGS + 1))
  fi
}

if [[ "${INSTALL_LEGACY_RENDERER:-0}" == 1 ]]; then
  check_mbgl_render_cli
fi

check_mbgl_native_deps() {
  command -v npm >/dev/null 2>&1 || return 0
  command -v ldd >/dev/null 2>&1 || return 0

  local npm_root addon ldd_output missing wrapper ld_prefix
  npm_root="$(npm root -g 2>/dev/null || true)"
  [[ -n "${npm_root}" && -d "${npm_root}/mbgl-renderer" ]] || return 0

  addon="$(find "${npm_root}/mbgl-renderer/node_modules/@maplibre/maplibre-gl-native" -name '*.node' -print -quit 2>/dev/null || true)"
  [[ -n "${addon}" ]] || return 0

  wrapper="$(command -v mbgl-render 2>/dev/null || true)"
  ld_prefix=""
  if [[ -n "${wrapper}" && -f "${wrapper}" ]]; then
    ld_prefix="$(sed -n 's/^default_ld="\([^"]*\)"$/\1/p' "${wrapper}" | head -n 1)"
  fi
  if [[ -n "${ld_prefix}" ]]; then
    ldd_output="$(LD_LIBRARY_PATH="${ld_prefix}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}" ldd "${addon}" 2>&1 || true)"
  else
    ldd_output="$(ldd "${addon}" 2>&1 || true)"
  fi
  missing="$(printf '%s\n' "${ldd_output}" | awk '/not found/ {print $1}' | sort -u | tr '\n' ' ')"
  if [[ -n "${missing}" ]]; then
    printf 'WARN %-12s missing native library: %s\n' "mbgl-deps" "${missing}"
    printf 'hint %-12s run devbox install, re-enter devbox shell, then devbox run doctor\n' "mbgl-deps"
    printf 'hint %-12s if libjpeg.so.8 remains missing on this distro, use a compatible mbgl-renderer build or MBGL_RENDER_TILE_COMMAND\n' "mbgl-deps"
    WARNINGS=$((WARNINGS + 1))
  else
    printf 'OK   %-12s native library deps\n' "mbgl-deps"
  fi
}

if [[ "${INSTALL_LEGACY_RENDERER:-0}" == 1 ]]; then
  check_mbgl_native_deps
fi

if PYTHONPATH="${REPO_ROOT}/backend/src" "${REPO_ROOT}/.venv/bin/python" -m \
    huavd_map_build.production.south.adapter.process.native_tools check; then
  printf 'OK   Native       checksum, protocol and real render self-test\n'
else
  printf 'FAIL Native       run make setup WORKDIR="%s" to fetch locked sources and build automatically\n' "${WORKDIR}"
  FAILURES=$((FAILURES + 1))
fi

if command -v pmtiles >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
  printf 'OK   %-12s %s\n' "raster-bake" "PMTiles convert path available"
else
  printf 'WARN %-12s missing pmtiles or python3 for raster bake MBTiles conversion\n' "raster-bake"
  WARNINGS=$((WARNINGS + 1))
fi

VENV_PYTHON="${REPO_ROOT}/.venv/bin/python"
VENV_BIN_DIR="${REPO_ROOT}/.venv/bin"

# Check pip. Prefer the project's .venv (avoids PEP 668's
# externally-managed-environment block in devbox shell where python3 is a
# Nix-managed immutable interpreter). Bare pip3/pip binaries may belong to a
# different Python than python3, so they only count as WARN.
if [[ -x "${VENV_PYTHON}" ]] && "${VENV_PYTHON}" -m pip --version >/dev/null 2>&1; then
  printf 'OK   %-12s %s\n' "pip" "$("${VENV_PYTHON}" -m pip --version | head -n 1)"
elif command -v python3 >/dev/null 2>&1 && python3 -m pip --version >/dev/null 2>&1; then
  printf 'OK   %-12s %s\n' "pip" "$(python3 -m pip --version | head -n 1)"
elif command -v pip3 >/dev/null 2>&1; then
  printf 'WARN %-12s %s\n' "pip" "pip3 binary present but python3 -m pip unavailable; pip may be from a different Python"
  WARNINGS=$((WARNINGS + 1))
elif command -v pip >/dev/null 2>&1; then
  printf 'WARN %-12s %s\n' "pip" "pip binary present but python3 -m pip unavailable; pip may be from a different Python"
  WARNINGS=$((WARNINGS + 1))
else
  printf 'WARN %-12s missing\n' "pip"
  WARNINGS=$((WARNINGS + 1))
fi

# Check fonttools. Also check the venv bin dir directly because .venv/bin
# is not on PATH by default.
if command -v fonttools >/dev/null 2>&1; then
  : # already covered by REQUIRED loop above
elif [[ -x "${VENV_BIN_DIR}/fonttools" ]]; then
  printf 'WARN %-12s found in %s but not on PATH; add %s to PATH or run devbox run setup\n' \
    "fonttools" "${VENV_BIN_DIR}/fonttools" "${VENV_BIN_DIR}"
  WARNINGS=$((WARNINGS + 1))
fi

if [[ -x "${VENV_PYTHON}" ]] && "${VENV_PYTHON}" -c 'import yaml' >/dev/null 2>&1; then
  printf 'OK   %-12s project Python+PyYAML\n' "yaml"
else
  printf 'FAIL %-12s project Python cannot import PyYAML; run make setup\n' "yaml"
  FAILURES=$((FAILURES + 1))
fi

fail_config() {
  printf 'FAIL %-12s %s\n' "regions" "$*"
  FAILURES=$((FAILURES + 1))
}

check_regions_config() {
  local regions
  if ! regions="$(regions_json)"; then
    fail_config "failed to parse config/regions.yaml"
    return
  fi

  if ! jq -r '
    def known_continent:
      . == "africa" or . == "antarctica" or . == "asia" or
      . == "australia-oceania" or . == "europe" or
      . == "north-america" or . == "south-america";

    def depth($region): ($region.id | split("/") | length);
    . as $root
    | ($root.regions // []) as $regions
    | ($regions | map(.id)) as $ids
    | ($regions | map(.slug // (.id | gsub("/"; "-")))) as $slugs
    | ($regions | map(.huavd.region_id // empty)) as $region_ids
    | ($root.naming.depth_segment_pattern // "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$") as $segment_pattern
    | ($root.naming.max_depth // 4) as $max_depth
    | [
        ($regions[] as $region
          | select(($region.geofabrik.parent_region != null) and (($ids | index($region.geofabrik.parent_region)) == null))
          | "parent_region does not exist for \($region.id): \($region.geofabrik.parent_region)"),
        ($regions[] as $region
          | select($region.geofabrik.parent_region == null and ($region.id | known_continent | not))
          | "root region must be a known continent: \($region.id)"),
        ($regions[] as $region
          | select(depth($region) > $max_depth)
          | "region exceeds naming.max_depth=\($max_depth): \($region.id)"),
        ($regions[] as $region
          | select(($region.id | split("/") | all(.[]; test($segment_pattern)) | not))
          | "region id segment does not match naming.depth_segment_pattern: \($region.id)"),
        ($slugs
          | group_by(.)[]
          | select(length > 1)
          | "duplicate slug: \(.[0])"),
        ($region_ids
          | group_by(.)[]
          | select(length > 1)
          | "duplicate huavd.region_id: \(.[0])"),
        ($regions[] as $region
          | select($region.huavd.region_id == null or $region.huavd.region_id == "")
          | "huavd.region_id missing: \($region.id)"),
        ($regions[] as $region
          | select(($region.huavd.region_id // "") != "" and (($region.huavd.region_id | test("^[a-z]{2}-[a-z0-9]{2,}(-[a-z0-9-]+)?$")) | not))
          | "huavd.region_id invalid: \($region.id) -> \($region.huavd.region_id)"),
        ($regions[] as $region
          | select($region.huavd.mapping_status == null or $region.huavd.mapping_status == "")
          | "huavd.mapping_status missing: \($region.id)")
      ]
      | if length == 0 then empty else .[] end
  ' "${regions}" > "$(configs_cache_dir)/regions-doctor-errors.txt"; then
    fail_config "regions.yaml structural validation query failed"
  fi

  if [[ -s "$(configs_cache_dir)/regions-doctor-errors.txt" ]]; then
    while IFS= read -r line; do
      fail_config "${line}"
    done < "$(configs_cache_dir)/regions-doctor-errors.txt"
  fi

  if ! jq -r '
    .regions as $regions
    | ($regions | map({key: .id, value: (.geofabrik.parent_region // null)}) | from_entries) as $parents
    | def has_cycle($id):
        def walk($current; $seen):
          if $current == null then false
          elif ($seen | index($current)) != null then true
          else walk($parents[$current]; $seen + [$current])
          end;
        walk($id; []);
      [$regions[] | select(has_cycle(.id)) | .id]
      | if length == 0 then empty else .[] end
  ' "${regions}" > "$(configs_cache_dir)/regions-cycle-errors.txt"; then
    fail_config "regions.yaml cycle validation query failed"
  fi

  if [[ -s "$(configs_cache_dir)/regions-cycle-errors.txt" ]]; then
    while IFS= read -r line; do
      fail_config "parent_region cycle detected at ${line}"
    done < "$(configs_cache_dir)/regions-cycle-errors.txt"
  fi

  if ((FAILURES == 0)); then
    printf 'OK   %-12s %s\n' "regions" "hierarchy and stable ids"
  fi
}

check_regions_config

check_tier_profiles_config() {
  local profiles profile
  if ! profiles="$(tier_profiles_json)"; then
    printf 'FAIL %-12s %s\n' "tier-profiles" "failed to parse config/tier-profiles.yaml"
    FAILURES=$((FAILURES + 1))
    return
  fi

  if ! jq -e --argjson region_ids "$(jq -c '[.regions[].id]' "$(regions_json)")" '
    . as $root
    | .schema_version == 1
    and (.profiles | type == "object" and length > 0)
    and (.regions | type == "object")
    and all(.regions | to_entries[];
      . as $entry
      | ($region_ids | index($entry.key)) != null
      and (($entry.value | type) == "object")
      and (($entry.value.build_profile | type) == "string" and ($entry.value.build_profile | length) > 0)
      and ($root.profiles[$entry.value.build_profile] != null)
    )
  ' "${profiles}" >/dev/null; then
    printf 'FAIL %-12s %s\n' "tier-profiles" "schema, region mapping, or profile reference invalid"
    FAILURES=$((FAILURES + 1))
    return
  fi

  while IFS= read -r profile; do
    if ! (tier_profile_validate "${profile}") >/dev/null 2>&1; then
      printf 'FAIL %-12s %s\n' "tier-profiles" "invalid profile: ${profile}"
      FAILURES=$((FAILURES + 1))
    fi
  done < <(jq -r '.profiles | keys[]' "${profiles}")

  if ((FAILURES == 0)); then
    printf 'OK   %-12s %s\n' "tier-profiles" "schema and profile rules"
  fi
}

check_tier_profiles_config

check_place_label_hierarchy_config() {
  if place_label_hierarchy_validate >/dev/null 2>&1; then
    printf 'OK   %-12s %s\n' "place-labels" "administrative hierarchy"
  else
    printf 'FAIL %-12s %s\n' "place-labels" "invalid administrative hierarchy"
    FAILURES=$((FAILURES + 1))
  fi
}

check_place_label_hierarchy_config

check_admin_line_hierarchy_config() {
  if admin_line_hierarchy_validate >/dev/null 2>&1; then
    printf 'OK   %-12s %s\n' "admin-lines" "administrative boundary hierarchy"
  else
    printf 'FAIL %-12s %s\n' "admin-lines" "invalid administrative boundary hierarchy"
    FAILURES=$((FAILURES + 1))
  fi
}

check_admin_line_hierarchy_config

check_derived_map_config() {
  local composites composite failures_before
  failures_before="${FAILURES}"
  if ! composites="$(composites_json)"; then
    printf 'FAIL %-12s %s\n' "derived-maps" "failed to parse config/composites.yaml"
    FAILURES=$((FAILURES + 1))
    return
  fi

  if ! jq -e '
    .schema_version == 2
    and (.composites | type == "array" and length > 0)
    and ([.composites[].id] | length == (unique | length))
  ' "${composites}" >/dev/null; then
    printf 'FAIL %-12s %s\n' "derived-maps" "schema or duplicate id invalid"
    FAILURES=$((FAILURES + 1))
    return
  fi

  while IFS= read -r composite; do
    if ! (derived_map_validate "${composite}") >/dev/null 2>&1; then
      printf 'FAIL %-12s %s\n' "derived-maps" "invalid derived map: ${composite}"
      FAILURES=$((FAILURES + 1))
    fi
  done < <(jq -r '.composites[].id' "${composites}")

  if (( FAILURES == failures_before )); then
    printf 'OK   %-12s %s\n' "derived-maps" "schema, source assets, and conflict policy"
  fi
}

check_derived_map_config

check_multilingual_config() {
  local glyphs styles icons
  if ! glyphs="$(glyphs_json)"; then
    printf 'FAIL %-12s %s\n' "glyphs" "failed to parse config/glyphs.yaml"
    FAILURES=$((FAILURES + 1))
    return
  fi
  if ! styles="$(styles_json)"; then
    printf 'FAIL %-12s %s\n' "styles" "failed to parse config/styles.yaml"
    FAILURES=$((FAILURES + 1))
    return
  fi
  if ! icons="$(icons_json)"; then
    printf 'FAIL %-12s %s\n' "icons" "failed to parse config/icons/manifest.yaml"
    FAILURES=$((FAILURES + 1))
    return
  fi

  if jq -e '
    .schema_version == 1
    and (.fonts | type == "array" and length > 0)
    and (.fonts | all(.id and .fontstack and .file))
    and (.ranges | type == "array" and length > 0)
    and (.ranges | all((.start | type == "number") and (.end | type == "number") and (.start <= .end)))
    and (.locales | type == "array" and length > 0)
    and (.locales | all(.tag and (.fonts | type == "array" and length > 0)))
  ' "${glyphs}" >/dev/null; then
    printf 'OK   %-12s %s\n' "glyphs" "schema"
  else
    printf 'FAIL %-12s %s\n' "glyphs" "schema invalid"
    FAILURES=$((FAILURES + 1))
  fi

  local configured_font missing_fonts=""
  while IFS= read -r configured_font; do
    [[ -n "${configured_font}" ]] || continue
    if [[ -f "${configured_font}" || -f "${REPO_ROOT}/${configured_font}" ]]; then
      continue
    fi
    case "$(basename -- "${configured_font}")" in
      NotoSans-Regular.ttf)
        [[ -f /usr/share/fonts/truetype/noto/NotoSans-Regular.ttf ]] && continue
        ;;
      NotoSansCJKsc-Regular.otf|NotoSansCJKjp-Regular.otf|NotoSansCJKkr-Regular.otf)
        [[ -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc ]] && continue
        [[ -f /usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf ]] && continue
        ;;
    esac
    missing_fonts+="${configured_font} "
  done < <(jq -r '.fonts[].file' "${glyphs}")
  if [[ -z "${missing_fonts}" ]]; then
    printf 'OK   %-12s %s\n' "glyph-fonts" "all configured fonts resolvable"
  else
    printf 'WARN %-12s missing: %s\n' "glyph-fonts" "${missing_fonts}"
    printf 'hint %-12s provide the configured fonts under %s/fonts or install compatible system Noto fonts before ROLE=*_raster GLYPH=1\n' "glyph-fonts" "${REPO_ROOT}"
    WARNINGS=$((WARNINGS + 1))
  fi

  if jq -e '
    .schema_version == 1
    and (.source.id | type == "string")
    and (.glyphs_url | strings | contains("{fontstack}") and contains("{range}.pbf"))
    and (.locales | type == "array" and length > 0)
    and (.locales | all(.tag and (.name_fields | type == "array" and length > 0)))
    and (.text_layers | type == "array" and length > 0)
  ' "${styles}" >/dev/null; then
    printf 'OK   %-12s %s\n' "styles" "schema"
  else
    printf 'FAIL %-12s %s\n' "styles" "schema invalid"
    FAILURES=$((FAILURES + 1))
  fi

  if jq -e '
    .schema_version == 1
    and (.sprite.icon_size | type == "number" and . > 0)
    and (.icons | type == "array" and length > 0)
    and (.icons | all((.id | type == "string" and length > 0) and (.shape | type == "string") and (.color | test("^#[0-9A-Fa-f]{6}$"))))
  ' "${icons}" >/dev/null; then
    printf 'OK   %-12s %s\n' "icons" "schema"
  else
    printf 'FAIL %-12s %s\n' "icons" "schema invalid"
    FAILURES=$((FAILURES + 1))
  fi
}

check_multilingual_config

routing_python="$(huavd_python)"
if PYTHONPATH="${REPO_ROOT}/backend/src" "${routing_python}" -m huavd_map_build \
    routing doctor --workdir="${WORKDIR}"; then
  printf 'OK   %-12s %s\n' "routeweft" "identity and build/verify probe"
else
  printf 'FAIL %-12s %s\n' "routeweft" "missing, invalid installation, or contract probe failed"
  printf 'install hints: WORKDIR="%s" ./scripts/setup-tools.sh (inside devbox shell)\n' "${WORKDIR}"
  printf 'install hints: or make setup WORKDIR="%s"; use the actual build/release WORKDIR\n' "${WORKDIR}"
  FAILURES=$((FAILURES + 1))
fi

if ((FAILURES > 0)); then
  printf 'doctor: FAIL (%d config error(s), %d missing item warning(s))\n' "${FAILURES}" "${WARNINGS}"
  exit "${HUAVD_EXIT_VERIFY}"
fi

if ((WARNINGS == 0)); then
  printf 'doctor: OK\n'
else
  printf 'doctor: WARN (%d missing item(s))\n' "${WARNINGS}"
  printf 'install hints: run devbox run setup, or run ./scripts/setup-tools.sh inside devbox shell. See README.md environment setup for manual commands.\n'
fi
