#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/config.sh
source "${SCRIPT_DIR}/lib/config.sh"

LOCALES="all"
FORCE=0

for arg in "$@"; do
  if parse_common_arg "${arg}"; then
    continue
  fi
  case "${arg}" in
    --locales=*) LOCALES="${arg#*=}" ;;
    --force) FORCE=1 ;;
    -h|--help)
      printf 'usage: %s --region=<id> [--yyyymm=YYYYMM] [--workdir=<path>] [--locales=all|tag[,tag...]] [--force]\n' "$0"
      exit 0
      ;;
    *) die "${HUAVD_EXIT_INPUT}" "unknown argument: ${arg}" ;;
  esac
done

require_cmd jq sha512sum
require_region "${REGION}"
normalize_session_vars

glyphs_config="$(glyphs_json)"
generator="$(jq -r '.generator.command // "build-glyphs"' "${glyphs_config}")"
require_cmd "${generator}"

glyphs_dir="$(build_glyphs_dir)"
if [[ -e "${glyphs_dir}" && "${FORCE}" != "1" ]]; then
  die "${HUAVD_EXIT_ERROR}" "glyph output already exists: ${glyphs_dir}; pass --force or clean first"
fi
if [[ -e "${glyphs_dir}" && "${FORCE}" == "1" ]]; then
  rm -rf "${glyphs_dir}"
fi
ensure_dir "${glyphs_dir}"

selected_locales() {
  if [[ -z "${LOCALES}" || "${LOCALES}" == "all" ]]; then
    jq -r '.locales[].tag' "${glyphs_config}"
  else
    tr ',' '\n' <<< "${LOCALES}" | while IFS= read -r tag; do
      [[ -n "${tag}" ]] || continue
      jq -e --arg tag "${tag}" 'any(.locales[]; .tag == $tag)' "${glyphs_config}" >/dev/null \
        || die "${HUAVD_EXIT_INPUT}" "unknown glyph locale: ${tag}"
      printf '%s\n' "${tag}"
    done
  fi
}

while IFS= read -r locale; do
  locale_dir="${glyphs_dir}/${locale}"
  ensure_dir "${locale_dir}"
  log_info "glyph locale ${locale}"

  while IFS= read -r font_id; do
    font_file="$(jq -r --arg id "${font_id}" '.fonts[] | select(.id == $id) | .file // empty' "${glyphs_config}")"
    fontstack="$(jq -r --arg id "${font_id}" '.fonts[] | select(.id == $id) | .fontstack // empty' "${glyphs_config}")"
    [[ -n "${font_file}" && -n "${fontstack}" ]] \
      || die "${HUAVD_EXIT_INPUT}" "glyph font ${font_id} is not configured"

    font_path="${REPO_ROOT}/${font_file}"
    require_file "${font_path}"
    log_info "glyph font ${fontstack}"
    "${generator}" "${font_path}" "${locale_dir}" \
      || die "${HUAVD_EXIT_ERROR}" "glyph generation failed for ${fontstack}"

    if [[ ! -d "${locale_dir}/${fontstack}" ]]; then
      log_warn "glyph generator did not create expected fontstack directory: ${locale_dir}/${fontstack}"
    fi
  done < <(jq -r --arg tag "${locale}" '.locales[] | select(.tag == $tag) | .fonts[]' "${glyphs_config}")
done < <(selected_locales)

find "${glyphs_dir}" -type f -name '*.pbf' -print0 | while IFS= read -r -d '' file; do
  write_sha512_file "${file}"
done

jq -n \
  --arg schema "huavd-map-glyphs/v1" \
  --arg session "${SESSION}" \
  --arg generated_at "$(timestamp_utc)" \
  --argjson available_locales "$(available_locales_json)" \
  --arg url_template "$(glyphs_url_template)" \
  '{
    schema: $schema,
    session: $session,
    generated_at: $generated_at,
    available_locales: $available_locales,
    url_template: $url_template
  }' > "${glyphs_dir}/manifest.json"

write_sha512_file "${glyphs_dir}/manifest.json"
log_info "glyphs OK: ${glyphs_dir}"
