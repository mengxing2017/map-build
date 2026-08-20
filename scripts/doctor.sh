#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

REQUIRED=(
  bash
  jq
  wget
  md5sum
  sha512sum
  sha256sum
  tar
  zip
  osmium
  tippecanoe
  pmtiles
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

if command -v yq >/dev/null 2>&1; then
  printf 'OK   %-12s %s\n' "yq" "$(cmd_version yq)"
elif command -v python3 >/dev/null 2>&1 && python3 -c 'import yaml' >/dev/null 2>&1; then
  printf 'OK   %-12s python3+PyYAML\n' "yaml"
elif command -v ruby >/dev/null 2>&1 && ruby -ryaml -e 'exit 0' >/dev/null 2>&1; then
  printf 'OK   %-12s ruby stdlib yaml\n' "yaml"
else
  printf 'WARN %-12s missing yq or python3+PyYAML\n' "yaml"
  WARNINGS=$((WARNINGS + 1))
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
