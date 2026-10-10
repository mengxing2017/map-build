#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
if [[ "${1:-}" == --help || "$#" == 0 ]]; then
  printf 'Usage: bash scripts/native-renderer-env.sh COMMAND [ARGUMENTS...]\nUses explicit Vulkan settings, or the local devbox software Vulkan profile.\n'
  exit 0
fi
profile="${HUAVD_NATIVE_PROFILE:-${REPO_DIR}/.devbox/nix/profile/default}"
if [[ -z "${VK_DRIVER_FILES:-}" ]]; then
  export VK_DRIVER_FILES="${profile}/share/vulkan/icd.d/lvp_icd.x86_64.json"
fi
[[ -f "$VK_DRIVER_FILES" ]] || { printf 'Missing Vulkan ICD: %s\n' "$VK_DRIVER_FILES" >&2; exit 2; }
driver="$(jq -er '.ICD.library_path' "$VK_DRIVER_FILES")"
[[ "$driver" == /* && -f "$driver" ]] || {
  printf 'This launcher requires an ICD with an existing absolute library_path.\n' >&2; exit 2;
}
[[ -f "$profile/lib/libvulkan.so.1" ]] || { printf 'Missing Vulkan loader in profile.\n' >&2; exit 2; }
loader_dir="$(dirname "$(readlink -f "$profile/lib/libvulkan.so.1")")"
driver_dir="$(dirname "$driver")"
export LD_LIBRARY_PATH="$loader_dir:$driver_dir:${LD_LIBRARY_PATH:-}"
export UV_USE_IO_URING="${UV_USE_IO_URING:-0}"
unset DISPLAY
exec "$@"
