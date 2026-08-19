#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SCRIPT_DIR}/lib/common.sh"
# shellcheck source=lib/pmtiles.sh
source "${SCRIPT_DIR}/lib/pmtiles.sh"

REGION_A="${1:?usage: $0 REGION_A REGION_B [YYYYMMDD]}"
REGION_B="${2:?usage: $0 REGION_A REGION_B [YYYYMMDD]}"
YYYYMMDD="${3:-$(date -u +%Y%m%d)}"
WORKDIR="${WORKDIR:-/tmp/huavd-map-build}"

SLUG_A="$(echo "${REGION_A}" | tr '/' '-')"
SLUG_B="$(echo "${REGION_B}" | tr '/' '-')"
BASE_A="${WORKDIR}/outputs/${SLUG_A}-${YYYYMMDD}.base.pmtiles"
BASE_B="${WORKDIR}/outputs/${SLUG_B}-${YYYYMMDD}.base.pmtiles"
STYLE_A="${WORKDIR}/outputs/${SLUG_A}-${YYYYMMDD}.style.json"
STYLE_B="${WORKDIR}/outputs/${SLUG_B}-${YYYYMMDD}.style.json"

echo "=== 1. PMTiles header 对比 ==="
echo "--- ${REGION_A} ---"
if [[ -f "${BASE_A}" ]]; then
  pmtiles show "${BASE_A}" | grep -E '^(min_zoom|max_zoom|center|bounds|zoom_levels)' || true
else
  echo "  (file not found: ${BASE_A})"
fi
echo "--- ${REGION_B} ---"
if [[ -f "${BASE_B}" ]]; then
  pmtiles show "${BASE_B}" | grep -E '^(min_zoom|max_zoom|center|bounds|zoom_levels)' || true
else
  echo "  (file not found: ${BASE_B})"
fi

echo
echo "=== 2. style.json layer 数量与 ID 对比 ==="
if [[ -f "${STYLE_A}" && -f "${STYLE_B}" ]]; then
  diff \
    <(jq -r '.layers[].id' "${STYLE_A}" | sort) \
    <(jq -r '.layers[].id' "${STYLE_B}" | sort) \
    && echo "OK: layers 完全一致" \
    || echo "WARN: layers 不一致"
else
  echo "  (style.json not found; skipping)"
fi

echo
echo "=== 3. style.json 关键 paint/layout 对比 ==="
if [[ -f "${STYLE_A}" && -f "${STYLE_B}" ]]; then
  paint_diff_found=0
  for layer in $(jq -r '.layers[].id' "${STYLE_A}"); do
    if ! diff -q \
      <(jq -S ".layers[] | select(.id == \"${layer}\") | .paint // {}" "${STYLE_A}") \
      <(jq -S ".layers[] | select(.id == \"${layer}\") | .paint // {}" "${STYLE_B}") \
      >/dev/null 2>&1; then
      echo "DIFF paint in ${layer}:"
      diff <(jq -S ".layers[] | select(.id == \"${layer}\") | .paint // {}" "${STYLE_A}") \
           <(jq -S ".layers[] | select(.id == \"${layer}\") | .paint // {}" "${STYLE_B}") || true
      paint_diff_found=1
    fi
  done
  if (( paint_diff_found == 0 )); then
    echo "OK: paint 完全一致"
  fi
else
  echo "  (style.json not found; skipping)"
fi

echo
echo "=== 4. base.pmtiles vector_layers 对比 ==="
if [[ -f "${BASE_A}" && -f "${BASE_B}" ]]; then
  diff \
    <(pmtiles show "${BASE_A}" | grep -E '^  [a-z_]+$' | sort) \
    <(pmtiles show "${BASE_B}" | grep -E '^  [a-z_]+$' | sort) \
    && echo "OK: vector_layers 一致" \
    || echo "WARN: vector_layers 不一致"
else
  echo "  (pmtiles not found; skipping)"
fi

echo
echo "=== 5. viewport metadata 对比 ==="
if [[ -f "${STYLE_A}" && -f "${STYLE_B}" ]]; then
  echo "--- ${REGION_A} ---"
  jq '.metadata["huavd:viewport"]' "${STYLE_A}" 2>/dev/null || echo "  (no viewport)"
  echo "--- ${REGION_B} ---"
  jq '.metadata["huavd:viewport"]' "${STYLE_B}" 2>/dev/null || echo "  (no viewport)"
fi
