# HUAVD Native renderer

Small Rust process boundary around the fixed MapLibre Native wrapper. The map
pipeline remains Python; this program renders one local XYZ tile to PNG.

Build with `bash scripts/setup-native-renderer.sh --help` from the repository
root, inside devbox. The script stages this crate next to a clean `wrapper`
source tree in an external build directory, applies the recorded patch, checks
the source baseline, and uses this Cargo.lock. The relative Cargo dependency
is intentional: do not run Cargo directly in this source directory without
preparing the sibling wrapper.

No core archives, downloaded sources or target caches belong in this directory.
The default engine is `maplibre-native-headless`, as configured in
`config/bake.yaml`. The Python CLI and `BAKE_RENDERER_ENGINE` in Makefile
can explicitly select a legacy engine.

See [the operation guide](../../docs/operations/native-renderer-build.md) for
build inputs, runtime environment, supported style subset, integration tests,
and the distinction between a generated candidate and a ready install bundle.
