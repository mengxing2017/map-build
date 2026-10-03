from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import time
import uuid
import zipfile

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.production.south.adapter.process.pmtiles_viewport import PmtilesViewportReader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId
from huavd_map_build.shared.kernel.identity import expand_roles


@dataclass(frozen=True, slots=True)
class BundleRequest:
    region: RegionId
    build_date: BuildDate
    session: SessionId
    role: str
    workdir: str
    format: str = "both"


class BundleService:
    def __init__(self, viewport: PmtilesViewportReader | None = None) -> None:
        self._viewport = viewport or PmtilesViewportReader()

    def run(self, request: BundleRequest) -> dict[str, object]:
        if request.format not in {"tar", "zip", "both"}:
            raise ValueError("format must be tar, zip, or both")
        started = time.monotonic()
        root = Path(request.workdir)
        outputs = root / "outputs"
        package = root / "cache" / "pack" / request.session.value
        if package.exists():
            shutil.rmtree(package)
        package.mkdir(parents=True)

        roles = list(expand_roles(request.role))
        if Role.RASTER_BAKE in roles and Role.BASE not in roles:
            roles.insert(0, Role.BASE)
        included: list[tuple[Role, ArtifactPaths, dict]] = []
        for role in roles:
            paths = ArtifactPaths(
                ArtifactIdentity(request.region, request.build_date, role), str(outputs)
            )
            if role is Role.BUILDING and request.role in {"both", "both_raster"} and not Path(paths.pmtiles).is_file():
                continue
            missing = [path for path in paths.core_files() if not Path(path).is_file()]
            if missing:
                raise ValueError(f"required bundle artifact is missing: {missing[0]}")
            if role is Role.RASTER_BAKE:
                self._verify_ready(paths)
            for source in paths.core_files():
                shutil.copy2(source, package / Path(source).name)
            included.append((role, paths, self._read_json(paths.manifest)))
        if not included:
            raise ValueError("bundle contains no artifacts")

        self._copy_resources(outputs, package, request.session.value)
        offline_maps = [self._offline_map(role, paths, manifest) for role, paths, manifest in included]
        self._validate_resources(package, offline_maps)
        first_record = included[0][2].get("huavd_record", {})
        install = self._install_document(
            request, offline_maps, str(first_record.get("bundle_id") or f"{request.session.value}-standard"),
            str(first_record.get("activation") or "manual"),
        )
        (package / "install.json").write_text(
            json.dumps(install, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self._write_manifests(package)
        archives = self._archives(outputs, package, request.session.value, request.format)
        metrics = {
            "schema_version": 1,
            "generated_at": self._timestamp(),
            "session": request.session.value,
            "role": request.role,
            "format": request.format,
            "copied_roles": len(included),
            "pack_directory": {
                "file_count": sum(1 for path in package.rglob("*") if path.is_file()),
                "bytes": sum(path.stat().st_size for path in package.rglob("*") if path.is_file()),
            },
            "phases_ms": {"total": int((time.monotonic() - started) * 1000)},
            "archives": archives,
        }
        metrics_path = outputs / f"{request.session.value}.pack.metrics.json"
        metrics_path.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._write_sidecar(metrics_path)
        return {**metrics, "package_directory": str(package)}

    def _offline_map(self, role: Role, paths: ArtifactPaths, manifest: dict) -> dict:
        record = manifest.get("huavd_record", {})
        digest = self._digest(Path(paths.pmtiles), "sha512")
        sidecar_digest = Path(paths.sha512).read_text(encoding="ascii").split()[0]
        if digest != sidecar_digest or digest != manifest.get("output", {}).get("sha512"):
            raise ValueError(f"artifact digest contract failed: {paths.pmtiles}")
        map_id = str(record.get("id") or paths.identity.stem)
        if role is Role.RASTER_BAKE and not map_id.endswith("-raster"):
            map_id += "-raster"
        tile_range = manifest.get("output", {}).get("tile_range")
        result = {
            "id": map_id,
            "name": record.get("name") or paths.identity.stem,
            "source-id": record.get("source_id"),
            "package-version": record.get("package_version"),
            "source-revision": record.get("source_revision"),
            "asset-role": record.get("asset_role"),
            "source-type": record.get("source_type"),
            "format": record.get("format") or "pmtiles",
            "coord-system": record.get("coord_system") or "EPSG:3857",
            "transport": record.get("transport") or "offline",
            "style-id": record.get("style_id") or "osm-dev",
            "available-locales": record.get("available_locales") or [],
            "style-locales": record.get("style_locales") or [],
            "glyphs-url": record.get("glyphs_url") or "huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf",
            "styles-url": record.get("styles_url") or (
                f"huavd-map://styles/{paths.identity.session.value}.style-raster.json"
                if role is Role.RASTER_BAKE else f"huavd-map://styles/{paths.identity.session.value}.style.json"
            ),
            "coverage-region-id": manifest.get("region"),
            "tile-range": ({"min-zoom": tile_range.get("min_zoom"), "max-zoom": tile_range.get("max_zoom"), "bounds": tile_range.get("bounds")} if tile_range else None),
            "checksum": {"algorithm": "sha512", "value": digest},
            "file": Path(paths.pmtiles).name,
            "released-at": record.get("released_at") or manifest.get("build_id") or self._timestamp(),
            "viewport": {key: value for key, value in self._viewport.read(paths.pmtiles).items() if key in {"center", "default_zoom"}},
        }
        required = ("id", "name", "source-id", "package-version", "asset-role", "source-type")
        if any(not result[key] for key in required):
            raise ValueError(f"manifest cannot produce install entry: {paths.manifest}")
        return result

    @staticmethod
    def _install_document(request: BundleRequest, maps: list[dict], bundle_id: str, activation: str) -> dict:
        scopes = {
            "base-vector": ["standard", "standard-buildings", "terrain-3d", "terrain-3d-buildings"],
            "building-vector": ["standard-buildings", "terrain-3d-buildings", "city-3d"],
            "raster-baked": ["standard", "standard-buildings"],
        }
        order_bases = {"raster-baked": 10, "base-vector": 20, "building-vector": 30}
        assets = [{
            "offline-map-id": item["id"], "asset-role": item["asset-role"],
            "required": item["asset-role"] in {"base-vector", "raster-baked"},
            "presentation-scope": scopes.get(item["asset-role"], []),
            "order": order_bases.get(item["asset-role"], 40) + index,
        } for index, item in enumerate(maps)]
        bounds = [item["tile-range"]["bounds"] for item in maps if item.get("tile-range")]
        coverage = [min(x[0] for x in bounds), min(x[1] for x in bounds), max(x[2] for x in bounds), max(x[3] for x in bounds)] if bounds else [-180, -90, 180, 90]
        base = next((item for item in maps if item["asset-role"] == "base-vector"), None)
        if base is None:
            raise ValueError("installable bundle requires a base-vector artifact")
        has_building = any(item["asset-role"] == "building-vector" for item in maps)
        return {
            "schema_version": "huavd-map-install/v1", "transfer_id": str(uuid.uuid4()),
            "session": request.session.value, "region": request.region.value,
            "generated_at": BundleService._timestamp(), "offline_maps": maps,
            "bundles": [{
                "id": bundle_id, "name": "Standard Map Bundle",
                "source-id": base["source-id"], "bundle-version": base["package-version"],
                "source-revision": base.get("source-revision"),
                "transport": base.get("transport", "offline"),
                "coord-system": base["coord-system"],
                "supported-presentations": ["standard"] + (["standard-buildings"] if has_building else []),
                "default-presentation": "standard", "style-locales": base.get("style-locales", []),
                "coverage-bounds": coverage, "coverage-region-ids": [],
                "license-status": "not-required", "activation": activation, "assets": assets,
            }],
        }

    @staticmethod
    def _copy_resources(outputs: Path, package: Path, session: str) -> None:
        for name in (f"{session}.style.json", f"{session}.style-raster.json"):
            source = outputs / name
            if source.is_file():
                (package / "styles").mkdir(exist_ok=True)
                shutil.copy2(source, package / "styles" / name)
                shutil.copy2(f"{source}.sha512", package / "styles" / f"{name}.sha512")
        for suffix, target in (("glyphs", "glyphs"), ("sprite", "sprite")):
            source = outputs / f"{session}.{suffix}"
            if source.is_dir():
                shutil.copytree(source, package / target)

    @staticmethod
    def _validate_resources(package: Path, maps: list[dict]) -> None:
        for item in maps:
            style = package / "styles" / item["styles-url"].removeprefix("huavd-map://styles/")
            if not style.is_file():
                raise ValueError(f"declared bundle style is missing: {style}")
            json.loads(style.read_text(encoding="utf-8"))
        if not any((package / "glyphs").rglob("*.pbf")):
            raise ValueError("bundle glyph resources are missing")
        if not (package / "sprite" / "sprite.json").is_file() or not (package / "sprite" / "sprite.png").is_file():
            raise ValueError("bundle sprite resources are missing")

    @staticmethod
    def _write_manifests(package: Path) -> None:
        files = sorted((path for path in package.rglob("*") if path.is_file()), key=lambda p: p.relative_to(package).as_posix().encode())
        for algorithm, name in (("sha256", "SHA256SUMS"), ("sha512", "SHA512SUMS")):
            lines = []
            for path in files:
                if path.name in {"SHA256SUMS", "SHA512SUMS"} or path.name.endswith(".sha512"):
                    continue
                lines.append(f"{BundleService._digest(path, algorithm)}  ./{path.relative_to(package).as_posix()}\n")
            (package / name).write_text("".join(lines), encoding="ascii")

    def _archives(self, outputs: Path, package: Path, session: str, format: str) -> dict:
        result: dict[str, int | None] = {"tar_bytes": None, "zip_bytes": None}
        if format in {"tar", "both"}:
            path = outputs / f"{session}.bundle.tar.gz"
            with tarfile.open(path, "w:gz") as archive:
                for child in sorted(package.rglob("*")):
                    archive.add(child, arcname=f"./{child.relative_to(package)}", recursive=False)
            self._write_sidecar(path); result["tar_bytes"] = path.stat().st_size
        if format in {"zip", "both"}:
            path = outputs / f"{session}.bundle.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                for child in sorted(package.rglob("*")):
                    if child.is_file(): archive.write(child, child.relative_to(package).as_posix())
            self._write_sidecar(path); result["zip_bytes"] = path.stat().st_size
        return result

    def _verify_ready(self, paths: ArtifactPaths) -> None:
        marker = self._read_json(paths.ready)
        expected = {"file": Path(paths.pmtiles).name, "sha512": self._digest(Path(paths.pmtiles), "sha512"), "manifest_sha512": self._digest(Path(paths.manifest), "sha512"), "attribution_sha512": self._digest(Path(paths.attribution), "sha512")}
        if marker.get("schema_version") != 1 or marker.get("role") != "raster_bake" or any(marker.get(key) != value for key, value in expected.items()):
            raise ValueError(f"raster ready marker does not match artifacts: {paths.ready}")

    @staticmethod
    def _read_json(path: str) -> dict:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def _digest(path: Path, algorithm: str) -> str:
        digest = hashlib.new(algorithm)
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""): digest.update(chunk)
        return digest.hexdigest()

    @classmethod
    def _write_sidecar(cls, path: Path) -> None:
        path.with_name(f"{path.name}.sha512").write_text(f"{cls._digest(path, 'sha512')}  {path.name}\n", encoding="ascii")

    @staticmethod
    def _timestamp() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
