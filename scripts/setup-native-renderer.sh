#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/lib/common.sh"
source "${SCRIPT_DIR}/lib/native-source.sh"

usage() {
  cat <<'HELP'
Usage: bash scripts/setup-native-renderer.sh [options]
  --build-dir=PATH       External build directory (default: project tools/native-build)
  --prefix=PATH          Installed version directory (default: project tools/maplibre-native)
  --wrapper-source=PATH  Existing local Git repository; export fixed source tree
  --core-source=PATH     Fixed core checkout ending in maplibre-native (source build)
  --amalgam=PATH         External prebuilt core archive (requires --headers)
  --headers=PATH         Matching core headers tarball
  --online              Fetch locked wrapper/core and submodules automatically; allow Cargo downloads
  --help
Never commits or copies large libraries into the project. Run inside devbox shell.
HELP
}

build_dir="${HUAVD_TOOLS_DIR}/native-build"
prefix="${HUAVD_NATIVE_TOOLS:-${HUAVD_TOOLS_DIR}/maplibre-native}"
wrapper_source=""
core_source=""
amalgam=""
headers=""
online=0
for argument in "$@"; do
  case "$argument" in
    --build-dir=*) build_dir="${argument#*=}" ;;
    --prefix=*) prefix="${argument#*=}" ;;
    --wrapper-source=*) wrapper_source="${argument#*=}" ;;
    --core-source=*) core_source="${argument#*=}" ;;
    --amalgam=*) amalgam="${argument#*=}" ;;
    --headers=*) headers="${argument#*=}" ;;
    --online) online=1 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$argument" >&2; exit 2 ;;
  esac
done
lock="${REPO_ROOT}/config/native-renderer.lock.json"
revision="$(jq -er '.wrapper_revision' "$lock")"
core_revision="$(jq -er '.core_revision' "$lock")"
repository="$(jq -er '.wrapper_repository' "$lock")"
patch="${REPO_ROOT}/patches/maplibre-native-rs/core-owned-run-loop.patch"
build_patch="${REPO_ROOT}/patches/maplibre-native-rs/explicit-amalgamation-mode.patch"
[[ "$(uname -s)" == Linux && "$(uname -m)" == x86_64 ]] || {
  printf 'Only Linux x86_64 is supported by this lock.\n' >&2; exit 2;
}
[[ -n "$build_dir" && -n "$prefix" ]] || exit 2
if [[ -z "$core_source" && -z "$amalgam" ]]; then
  if [[ "$online" != 1 ]]; then
    printf 'No local core supplied; use --online to fetch locked Native repositories.\n' >&2
    exit 2
  fi
  core_source="$build_dir/core-$core_revision/maplibre-native"
  core_repository="$(jq -er '.core_repository' "$lock")"
  native_checkout_locked "$core_repository" "$core_revision" "$core_source"
fi
[[ -z "$core_source" || -z "$amalgam" ]] || exit 2
if [[ -n "$amalgam" ]]; then
  [[ -f "$amalgam" && -f "$headers" ]] || { printf 'Missing archive or headers.\n' >&2; exit 2; }
  amalgam="$(readlink -f "$amalgam")"
  headers="$(readlink -f "$headers")"
  expected="$(jq -er '.amalgam_sha256' "$lock")"
  actual="$(sha256sum "$amalgam")"
  [[ "${actual%% *}" == "$expected" ]] || { printf 'Core checksum mismatch.\n' >&2; exit 2; }
  expected="$(jq -er '.headers_sha256' "$lock")"
  actual="$(sha256sum "$headers")"
  [[ "${actual%% *}" == "$expected" ]] || { printf 'Headers checksum mismatch.\n' >&2; exit 2; }
else
  core_source="$(readlink -f "$core_source")"
  [[ "$core_source" == */maplibre-native ]] || exit 2
  [[ "$(git -C "$core_source" rev-parse HEAD)" == "$core_revision" ]] || exit 2
  [[ -z "$(native_run_stage core-source-status git -C "$core_source" status --porcelain)" ]] || {
    printf 'Source core must be clean.\n' >&2; exit 2;
  }
  if [[ "$online" == 1 ]]; then
    native_run_stage core-submodules timeout "${NATIVE_SUBMODULE_TIMEOUT_SECONDS:-1800}" \
      git -c http.lowSpeedLimit=1024 -c http.lowSpeedTime=60 \
      -C "$core_source" submodule update --init --recursive --depth 1
  fi
  submodules="$(native_run_stage core-submodule-status git -C "$core_source" submodule status --recursive)"
  if [[ "$online" == 0 ]] && printf '%s\n' "$submodules" | grep -Eq '^[-+U]'; then
    printf 'Offline source build requires initialized matching submodules.\n' >&2; exit 2
  fi
fi
mkdir -p "$build_dir"
build_dir="$(cd "$build_dir" && pwd)"
wrapper="$build_dir/wrapper"
wrapper_incomplete=0
if [[ "$online" == 1 && -z "$wrapper_source" && -d "$wrapper" ]] \
    && ! git -C "$wrapper" config --get huavd.wrapperRevision >/dev/null 2>&1 \
    && ! git -C "$wrapper" rev-parse --verify HEAD >/dev/null 2>&1; then
  wrapper_incomplete=1
fi
if [[ ! -d "$wrapper" || "$wrapper_incomplete" == 1 ]]; then
  if [[ -n "$wrapper_source" ]]; then
    mkdir -p "$wrapper"
    git -C "$wrapper_source" archive "$revision" | tar -xf - -C "$wrapper"
    git -C "$wrapper" init -q
    git -C "$wrapper" add -f .
    tree="$(git -C "$wrapper_source" rev-parse "$revision^{tree}")"
    [[ "$(git -C "$wrapper" write-tree)" == "$tree" ]] || exit 2
    git -C "$wrapper" config huavd.wrapperRevision "$revision"
    git -C "$wrapper" config huavd.wrapperTree "$tree"
  elif [[ "$online" == 1 ]]; then
    native_checkout_locked "$repository" "$revision" "$wrapper"
  else
    printf 'Offline preparation requires --wrapper-source.\n' >&2; exit 2
  fi
  if [[ -z "$wrapper_source" ]]; then
    native_run_stage wrapper-checkout git -C "$wrapper" checkout --detach "$revision"
  fi
fi
if recorded_revision="$(git -C "$wrapper" config --get huavd.wrapperRevision)"; then
  [[ "$recorded_revision" == "$revision" ]] || exit 2
  [[ "$(git -C "$wrapper" write-tree)" == "$(git -C "$wrapper" config --get huavd.wrapperTree)" ]] || exit 2
else
  [[ "$(git -C "$wrapper" rev-parse HEAD)" == "$revision" ]] || exit 2
  [[ "$(git -C "$wrapper" write-tree)" == "$(git -C "$wrapper" rev-parse HEAD^{tree})" ]] || exit 2
fi
for recorded_patch in "$patch" "$build_patch"; do
  if git -C "$wrapper" apply --reverse --check "$recorded_patch" 2>/dev/null; then
    printf 'Wrapper already contains recorded patch: %s\n' "$(basename "$recorded_patch")"
  elif git -C "$wrapper" apply --check "$recorded_patch"; then
    git -C "$wrapper" apply "$recorded_patch"
  else
    printf 'Wrapper patch cannot be applied safely: %s\n' "$recorded_patch" >&2; exit 2
  fi
done
# Reject inherited diagnostic edits or any unrecorded source changes.
actual_patch="$(git -C "$wrapper" diff --binary)"
expected_patch="$(cat "$build_patch" "$patch")"
[[ "$actual_patch" == "$expected_patch" ]] || {
  printf 'Wrapper differs from the recorded minimal patch.\n' >&2; exit 2;
}
mkdir -p "$build_dir/cli/src"
cp "${REPO_ROOT}/tools/native-render/Cargo.toml" "$build_dir/cli/Cargo.toml"
cp "${REPO_ROOT}/tools/native-render/src/main.rs" "$build_dir/cli/src/main.rs"
if [[ -f "${REPO_ROOT}/tools/native-render/Cargo.lock" ]]; then
  cp "${REPO_ROOT}/tools/native-render/Cargo.lock" "$build_dir/cli/Cargo.lock"
fi
export HUAVD_NATIVE_PATCH_SHA256="$(cat "$build_patch" "$patch" | sha256sum | cut -d ' ' -f 1)"
export HUAVD_NATIVE_SOURCE_SHA256="$(sha256sum "$build_dir/cli/src/main.rs" | cut -d ' ' -f 1)"
unset MLN_DIAGNOSTIC_CORE_CACHE MLN_SYSTEM MLN_CORE_LIBRARY_NO_AMALGAM
if [[ -n "$amalgam" ]]; then
  export MLN_PRECOMPILE=1 MLN_CORE_LIBRARY_PATH="$amalgam" MLN_CORE_LIBRARY_HEADERS_PATH="$headers"
  unset MLN_LOCAL_REPOSITORY
else
  export MLN_PRECOMPILE=0 MLN_CORE_LIBRARY_USE_AMALGAM=0 MLN_LOCAL_REPOSITORY="$core_source"
  unset MLN_CORE_LIBRARY_PATH MLN_CORE_LIBRARY_HEADERS_PATH
fi
export CMAKE_BUILD_PARALLEL_LEVEL="${CMAKE_BUILD_PARALLEL_LEVEL:-2}"
export NIX_HARDENING_ENABLE="${NIX_HARDENING_ENABLE:-stackprotector}"
cargo_options=(--offline)
[[ "$online" == 0 ]] || cargo_options=()
[[ ! -f "$build_dir/cli/Cargo.lock" ]] || cargo_options+=(--locked)
if ! cargo --version >/dev/null 2>&1; then
  native_run_stage rust-toolchain rustup default stable
fi
native_run_stage cargo-build cargo build "${cargo_options[@]}" --release --manifest-path "$build_dir/cli/Cargo.toml"
native_run_stage cargo-test cargo test "${cargo_options[@]}" --release --manifest-path "$build_dir/cli/Cargo.toml"
binary="$build_dir/cli/target/release/huavd-native-render"
"$binary" --version
digest="$(sha256sum "$binary" | cut -d ' ' -f 1)"
destination="$prefix/$digest"
if [[ -e "$destination" ]]; then
  installed_digest="$(sha256sum "$destination/bin/huavd-native-render")"
  [[ "${installed_digest%% *}" == "$digest" && -s "$destination/build-info.json" ]] || {
    printf 'Existing installation is incomplete or corrupt: %s\n' "$destination" >&2; exit 2;
  }
  printf 'Verified existing installation: %s\n' "$destination"
  HUAVD_NATIVE_TOOLS="$prefix" HUAVD_NATIVE_INSTALLATION="$destination" \
    PYTHONPATH="${REPO_ROOT}/backend/src" native_run_stage validate-and-activate "${REPO_ROOT}/.venv/bin/python" -m \
    huavd_map_build.production.south.adapter.process.native_tools setup
  exit 0
fi
mkdir -p "$prefix"
install_staging="$(mktemp -d "$prefix/.install.XXXXXX")"
# Leave a failed staging directory for diagnosis; never expose it as a version.
mkdir -p "$install_staging/bin" "$install_staging/licenses"
cp "$binary" "$install_staging/bin/huavd-native-render"
cp "$wrapper/LICENSE-MIT" "$wrapper/LICENSE-APACHE" "$install_staging/licenses/"
cp "$lock" "$install_staging/source-lock.json"
cat "$build_patch" "$patch" > "$install_staging/wrapper.patch"
cp "$build_dir/cli/Cargo.lock" "$install_staging/Cargo.lock"
"$binary" --version > "$install_staging/build-info.json"
printf '%s  bin/huavd-native-render\n' "$digest" > "$install_staging/binary.sha256"
ldd "$binary" > "$install_staging/ldd.txt"
if grep -q 'not found' "$install_staging/ldd.txt"; then
  printf 'Missing runtime libraries; staging retained: %s\n' "$install_staging" >&2; exit 2
fi
mv -T "$install_staging" "$destination"
HUAVD_NATIVE_TOOLS="$prefix" HUAVD_NATIVE_INSTALLATION="$destination" \
  PYTHONPATH="${REPO_ROOT}/backend/src" native_run_stage validate-and-activate "${REPO_ROOT}/.venv/bin/python" -m \
  huavd_map_build.production.south.adapter.process.native_tools setup
printf 'Installed: %s/bin/huavd-native-render\nRun --self-test in the target Vulkan environment before use.\n' "$destination"
