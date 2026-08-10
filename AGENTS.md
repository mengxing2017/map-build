# AGENTS.md

This file gives AI coding agents the project context needed to make safe,
useful changes in this repository.

## Project Purpose

`huavd-map-build` builds offline vector map packages from Geofabrik OpenStreetMap
`.osm.pbf` extracts. The pipeline converts selected OSM tags into GeoJSONSeq
layers, builds PMTiles with tippecanoe, writes HUAVD metadata and manifests, then
packages the artifacts for offline distribution.

The repository is shell-script based. There is no application server or frontend
runtime in this project.

## Primary Environment

Use devbox for normal work:

```bash
devbox shell
devbox run setup
devbox run doctor
```

`devbox shell` only sets up the environment and `PATH`. It must not perform heavy
downloads or tool builds on entry. Tool installation is intentionally behind
`devbox run setup` / `make setup`.

Important external tools:

- `osmium`: PBF filtering and GeoJSONSeq export.
- `tippecanoe`: GeoJSONSeq to MBTiles/PMTiles vector tile generation.
- `pmtiles`: PMTiles metadata/header inspection and editing.
- `jq`, `yq`, `wget`, `tar`, `zip`, `sha512sum`, `md5sum`.

Tippecanoe official releases do not provide Linux binaries for this workflow.
`scripts/setup-tools.sh` builds it from source by default. If
`/tmp/tippecanoe.tar.gz` exists, setup reuses that local source tarball instead of
downloading again. Override with:

```bash
TIPPECANOE_SOURCE_TARBALL=/path/to/tippecanoe.tar.gz devbox run setup
TIPPECANOE_BINARY_URL=https://example.invalid/tippecanoe.tar.gz devbox run setup
```

When building inside devbox/Nix, do not mix system `/usr/lib` sqlite/zlib with
the Nix compiler. `devbox.json` declares sqlite/zlib `out` and `dev` outputs so
the setup script can pass consistent include, lib, and rpath flags.

## Common Commands

```bash
make setup
make doctor
make fetch REGION=china/guangxi
make build REGION=china/guangxi YYYYMM=202607 ROLE=both
make verify REGION=china/guangxi YYYYMM=202607 ROLE=both
make pack SESSION=china-guangxi-202607 ROLE=both FORMAT=both
make clean SESSION=china-guangxi-202607 ROLE=both
```

Direct script entry points are also supported:

```bash
./scripts/fetch.sh --region=china/guangxi
./scripts/build.sh --input=mirror/guangxi-latest.osm.pbf --region=china/guangxi --yyyymm=202607 --role=both
./scripts/verify.sh --region=china/guangxi --yyyymm=202607 --role=both
./scripts/pack.sh --session=china-guangxi-202607 --role=both --format=both
```

Avoid running `make fetch` or a full `make build` unless the task requires it.
They may download large PBF files and perform long tile builds.

## Runtime Variables

Defaults are defined in `Makefile` and `scripts/lib/common.sh`.

- `WORKDIR`: workspace for generated data, default `/tmp/huavd-map-build`.
- `REGION`: configured region id, default `china/guangxi`.
- `YYYYMM`: build month in `YYYYMM` format, default current UTC month.
- `SESSION`: `{region-slug}-{yyyymm}`, for example `china-guangxi-202607`.
- `ROLE`: `base`, `building`, `both`, `dem`, or `all`.
- `FORMAT`: `tar`, `zip`, or `both` for packaging.
- `INPUT`: PBF input path for `make build`; relative paths are resolved under
  `WORKDIR` when appropriate.

Output naming uses:

```text
${WORKDIR}/outputs/{region-slug}-{yyyymm}.{role}.pmtiles
${WORKDIR}/outputs/{region-slug}-{yyyymm}.{role}.pmtiles.sha512
${WORKDIR}/outputs/{region-slug}-{yyyymm}.{role}.manifest.json
${WORKDIR}/outputs/{region-slug}-{yyyymm}.{role}.attribution.json
${WORKDIR}/outputs/{region-slug}-{yyyymm}.bundle.tar.gz
${WORKDIR}/outputs/{region-slug}-{yyyymm}.bundle.zip
```

## Pipeline

`scripts/build.sh` orchestrates the main build:

1. Validate region and input PBF.
2. Link input to `${WORKDIR}/staging/${SESSION}/source.osm.pbf`.
3. Run `scripts/tags-filter.sh` to create per-layer filtered PBFs.
4. Run `scripts/export.sh` to export per-layer GeoJSONSeq files.
5. Run `scripts/normalize.sh` to normalize feature properties.
6. Run `scripts/tippecanoe.sh` for each requested role.
7. Run `scripts/metadata.sh` to edit PMTiles metadata.
8. Run `scripts/manifest.sh` and `scripts/attribution.sh`.
9. Run `scripts/verify.sh`.
10. Write `.sha512` sidecars.

The `building` role is optional. It only builds when the region has
`huavd.asset_role: building-vector` and `huavd.source_type: derived-building` in
`config/regions.yaml`. If `ROLE=both` and building is not enabled, the build skips
building with a warning.

The `dem` role is a separate offline DEM asset path. It must use authorized local
or internal mirror inputs declared in `config/dem.yaml`; do not add default public
DEM download URLs unless licensing, mapping compliance, offline redistribution,
and export constraints are confirmed. DEM PMTiles metadata must include
`dem-encoding` and `huavd:vertical-datum`. Packaging must put DEM into
`install.json.offline_maps[]` as `asset-role=dem-raster` and link it through
bundle assets, not through private top-level manifest fields.

## Repository Map

- `README.md`: user-facing environment and install instructions.
- `AGENTS.md`: AI-facing project context and operating guide.
- `Makefile`: stable command entry points.
- `devbox.json`: development tool declarations and devbox scripts.
- `scripts/lib/common.sh`: shared path, session, logging, validation, and version helpers.
- `scripts/lib/config.sh`: YAML-to-JSON config loading and accessors.
- `scripts/lib/pmtiles.sh`: PMTiles header/metadata inspection helpers.
- `scripts/setup-tools.sh`: manual installation logic for osmium, tippecanoe, and pmtiles.
- `scripts/doctor.sh`: checks whether required commands are installed and runnable.
- `scripts/fetch.sh`: downloads configured Geofabrik PBF and MD5 into `WORKDIR/mirror`.
- `scripts/tags-filter.sh`: runs `osmium tags-filter` per layer.
- `scripts/export.sh`: stages export config and runs `osmium export`.
- `scripts/normalize.sh`: trims and normalizes GeoJSONSeq properties.
- `scripts/tippecanoe.sh`: resolves tippecanoe settings and creates PMTiles.
- `scripts/metadata.sh`: writes PMTiles metadata.
- `scripts/manifest.sh`: writes build manifest JSON.
- `scripts/attribution.sh`: writes attribution JSON.
- `scripts/verify.sh`: validates PMTiles headers, metadata, manifests, and hashes.
- `scripts/pack.sh`: packages artifacts into tar/zip bundles.
- `config/regions.yaml`: region catalog and HUAVD source metadata.
- `config/dem.yaml`: authorized DEM source, encoding, license, and vertical datum metadata.
- `config/layers.yaml`: source layer definitions, tag filters, and final fields.
- `config/tippecanoe.yaml`: tippecanoe defaults, high-density overrides, and building role settings.
- `config/export-config/*.json`: osmium export config per layer.
- `config/regions/`: optional `.poly` files for derived regional extracts.

## Configuration Coupling

Layer changes usually require coordinated edits:

- Add or rename a layer in `config/layers.yaml`.
- Add or rename the matching `config/export-config/{layer}.json`.
- Include the layer in `config/tippecanoe.yaml` `defaults.source_layers` when it
  should appear in the base PMTiles.
- Ensure `normalize.sh` preserves the intended final fields via
  `source_layers.*.final_fields`.
- Update verify expectations if the number of vector layers changes.

Region changes usually require:

- A new or updated entry in `config/regions.yaml`.
- Valid `geofabrik.pbf_url`, `geofabrik.md5_url`, and `geofabrik.basename`.
- HUAVD fields such as `source_id`, `asset_role`, `source_type`, `style_id`, and
  `package_version_template` when artifacts need complete metadata.
- Reviewed `.poly` files in `config/regions/` only when an extract workflow uses
  polygon fallback. The scripts do not download `.poly` files automatically.

Tippecanoe changes usually belong in `config/tippecanoe.yaml` rather than hard
coded shell logic. Keep `scripts/tippecanoe.sh` as a resolver/runner unless a new
tippecanoe CLI feature cannot be expressed through config.

## Development Rules

- Shell scripts use Bash with `set -euo pipefail`; keep new scripts consistent.
- Source shared helpers with the existing pattern near the top of each script.
- Prefer adding validation and explicit error messages over silent fallbacks.
- Do not use `|| true` to hide installation, build, or verification failures.
- Keep generated outputs out of the repository; use `WORKDIR`.
- Do not commit downloaded PBFs, PMTiles, build caches, or `/tmp` artifacts.
- Do not change output naming lightly; pack, verify, manifest, and downstream
  systems depend on the current file stems.
- Avoid destructive commands against user data. `make clean` only removes the
  current session's known artifacts under `WORKDIR`.
- Network-heavy commands should be treated as expensive and should be avoided
  during routine code edits unless explicitly needed.

## Validation Checklist

For script or config changes, run at least:

```bash
bash -n scripts/*.sh scripts/lib/*.sh
jq . devbox.json >/dev/null
devbox run doctor
```

For config changes, also check YAML parsing through the project helpers:

```bash
WORKDIR=/tmp/huavd-map-build ./scripts/doctor.sh
WORKDIR=/tmp/huavd-map-build ./scripts/build.sh --help
WORKDIR=/tmp/huavd-map-build ./scripts/verify.sh --help
```

For end-to-end behavior, use the smallest available region/input. A full build
requires a real `.osm.pbf` and may take significant time.

## Known Pitfalls

- `tippecanoe --version` writes its version to stderr; version helpers must
  capture stderr from successful version commands.
- `libsqlite3.so.0` or sqlite/zlib header failures usually indicate mixed system
  and Nix dependencies, or missing sqlite/zlib `dev` outputs.
- `pmtiles` v1.31.2 can be installed from the GitHub release tarball. If falling
  back to Go, the CLI module path is `github.com/protomaps/go-pmtiles@v1.31.2`.
- `devbox.lock` may mention store paths that are not installed locally until
  `devbox install` or `devbox run setup` fetches them.
- The PMTiles verifier expects PMTiles v3, MVT tile type, gzip compression, and
  metadata vector layer counts of 12 for `base` and 1 for `building`.
