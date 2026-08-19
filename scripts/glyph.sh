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
      printf 'usage: %s --region=<id> [--yyyymmdd=YYYYMMDD] [--workdir=<path>] [--locales=all|tag[,tag...]] [--force]\n' "$0"
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
if [[ "${generator}" == "build-glyphs" && -x "${HOME}/.cargo/bin/versatiles_glyphs" ]]; then
  PATH="${HOME}/.cargo/bin:${PATH}"
  export PATH
fi
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

resolve_font_path() {
  local configured="$1"
  local basename repo_path

  if is_abs_path "${configured}" && [[ -f "${configured}" ]]; then
    printf '%s\n' "${configured}"
    return
  fi

  repo_path="${REPO_ROOT}/${configured}"
  if [[ -f "${repo_path}" ]]; then
    printf '%s\n' "${repo_path}"
    return
  fi

  basename="$(basename -- "${configured}")"
  case "${basename}" in
    NotoSans-Regular.ttf)
      [[ -f /usr/share/fonts/truetype/noto/NotoSans-Regular.ttf ]] \
        && printf '%s\n' /usr/share/fonts/truetype/noto/NotoSans-Regular.ttf \
        && return
      ;;
    NotoSansCJKsc-Regular.otf|NotoSansCJKjp-Regular.otf|NotoSansCJKkr-Regular.otf)
      [[ -f /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc ]] \
        && printf '%s\n' /usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc \
        && return
      [[ -f /usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf ]] \
        && printf '%s\n' /usr/share/fonts/opentype/source-han-cjk/SourceHanSansSC-Regular.otf \
        && return
      ;;
  esac

  printf '%s\n' "${repo_path}"
}

install_generated_fontstack() {
  local generated_dir="$1"
  local target_dir="$2"
  local source_dir=""

  if [[ -d "${generated_dir}/$(basename -- "${target_dir}")" ]]; then
    source_dir="${generated_dir}/$(basename -- "${target_dir}")"
  else
    source_dir="$(find "${generated_dir}" -mindepth 1 -maxdepth 1 -type d -exec sh -c 'find "$1" -type f -name "*.pbf" -print -quit | grep -q .' sh {} \; -print -quit)"
  fi

  [[ -n "${source_dir}" && -d "${source_dir}" ]] \
    || die "${HUAVD_EXIT_ERROR}" "glyph generator did not create pbf output under ${generated_dir}"

  rm -rf "${target_dir}"
  ensure_dir "${target_dir}"
  cp -R "${source_dir}/." "${target_dir}/" \
    || die "${HUAVD_EXIT_DISK}" "failed to install glyph fontstack: ${target_dir}"
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

    font_path="$(resolve_font_path "${font_file}")"
    require_file "${font_path}"
    log_info "glyph font ${fontstack}"
    tmp_dir="${glyphs_dir}/.tmp-${locale}-${font_id}-$$"
    rm -rf "${tmp_dir}"
    ensure_dir "${tmp_dir}"
    "${generator}" "${font_path}" "${tmp_dir}" \
      || die "${HUAVD_EXIT_ERROR}" "glyph generation failed for ${fontstack}"
    install_generated_fontstack "${tmp_dir}" "${locale_dir}/${fontstack}"
    rm -rf "${tmp_dir}"
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
