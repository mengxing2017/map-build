from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re

from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.delivery.domain.attribution import AttributionDocument, AttributionSource
from huavd_map_build.delivery.domain.manifest import SourceEvidence, valid_source_sha256
from huavd_map_build.delivery.south.port.manifest import ManifestEvidenceReader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


@dataclass(frozen=True, slots=True)
class SourceProvenance:
    vendor: str
    url: str | None
    basename: str | None
    revision_stem: str | None
    catalog_revision_stem: str | None
    evidence: SourceEvidence


def manifest_source(document: object) -> AttributionSource:
    source = document.get("source") if isinstance(document, dict) else None
    if not isinstance(source, dict) or "vendor" not in source or "url" not in source:
        raise ValueError("manifest source is missing or incomplete; rebuild the manifest")
    return AttributionDocument.osm(source["vendor"], source["url"]).sources[0]


def read_manifest_source(path: str) -> AttributionSource:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise ValueError(f"cannot read manifest {path}; generate or rebuild it first: {error}") from error
    return manifest_source(document)


def validated_base_source(
    document: dict, *, region: RegionId, build_date: BuildDate,
    actual_size: int, actual_sha512: str,
) -> dict:
    manifest_source(document)
    record, output = document.get("huavd_record"), document.get("output")
    stem = f"{region.slug}-{build_date.value}.base"
    if (
        document.get("schema") != "huavd-map-build/v1"
        or document.get("region") != region.value
        or document.get("yyyymmdd") != build_date.value
        or not isinstance(record, dict)
        or record.get("asset_role") != "base-vector"
        or record.get("source_type") != "osm-pbf"
    ):
        raise ValueError("base manifest identity does not match requested region/date/role")
    if not isinstance(output, dict) or (
        output.get("path") != f"outputs/{stem}.pmtiles"
        or output.get("size_bytes") != actual_size
        or output.get("sha512") != actual_sha512
    ):
        raise ValueError("base manifest output size or SHA-512 does not match base PMTiles")
    source = document["source"]
    if not {
        "vendor", "url", "size_bytes", "downloaded_at", "md5", "sha256",
        "osm_timestamp",
    } <= source.keys():
        raise ValueError("base manifest source evidence is incomplete")
    if source["size_bytes"] is not None and (
        type(source["size_bytes"]) is not int or source["size_bytes"] < 0
    ):
        raise ValueError("base manifest source size is invalid")
    if source["md5"] is not None and (
        not isinstance(source["md5"], str)
        or re.fullmatch(r"[0-9a-f]{32}", source["md5"]) is None
    ):
        raise ValueError("base manifest source MD5 is invalid")
    if not valid_source_sha256(source["sha256"]):
        raise ValueError("base manifest source SHA-256 is invalid")
    return source


def raster_source_revision(
    catalog: CatalogService, base_manifest: dict, region: RegionId, build_date: BuildDate
) -> str:
    source = manifest_source(base_manifest)
    record = base_manifest.get("huavd_record")
    revision = record.get("source_revision") if isinstance(record, dict) else None
    if not isinstance(revision, str) or not revision.strip():
        raise ValueError("base manifest source_revision is required")
    if source.vendor == "local":
        return revision
    entry = catalog.region(region).geofabrik
    if not entry.basename:
        raise ValueError(f"Geofabrik raster source requires own catalog basename: {region.value}")
    if source.url != entry.pbf_url:
        raise ValueError("base manifest Geofabrik URL does not match region catalog")
    provenance = SourceProvenance(
        source.vendor, source.url, entry.basename, _stem(entry.basename),
        _stem(entry.basename), SourceEvidence(None, None, None),
    )
    if revision != source_revision(provenance, region, build_date, Role.BASE):
        raise ValueError("base manifest Geofabrik source_revision does not match region/date")
    return source_revision(provenance, region, build_date, Role.RASTER_BAKE)


def _stem(basename: str | None) -> str | None:
    if not basename:
        return None
    return basename.removesuffix(".osm.pbf").removesuffix("-latest") or None


def resolve_source(
    catalog: CatalogService, *, region: RegionId, workdir: str, session: SessionId,
    evidence: ManifestEvidenceReader, require_source: bool = True,
) -> SourceProvenance:
    root = Path(workdir.rstrip("/"))
    staged = root / "staging" / session.value / "source.osm.pbf"
    entry = catalog.region(region)
    catalog_basename = entry.geofabrik.basename
    mirror = root / "mirror" / catalog_basename if catalog_basename else None
    try:
        target = staged.resolve() if staged.exists() else None
        mirror_target = (
            mirror.resolve() if mirror is not None and mirror.is_file() else None
        )
    except OSError as error:
        raise ValueError(f"cannot resolve source PBF paths: {error}") from error
    catalog_input = bool(
        target is not None and mirror_target is not None
        and target == mirror_target
    )
    sidecar = mirror if catalog_input else target
    if target is None and not require_source and not staged.is_symlink():
        read = SourceEvidence(None, None, None)
    else:
        read = evidence.source(
            str(staged), f"{sidecar}.md5" if sidecar is not None else None
        )
    url = entry.geofabrik.pbf_url
    downloaded = bool(catalog_input and url)
    basename = catalog_basename if catalog_input else (
        target.name if target is not None else None
    )
    return SourceProvenance(
        vendor="geofabrik" if downloaded else "local",
        url=url if downloaded else None,
        basename=basename,
        revision_stem=_stem(basename),
        catalog_revision_stem=_stem(catalog_basename),
        evidence=read,
    )


def source_revision(
    source: SourceProvenance, region: RegionId, build_date: BuildDate, role: Role
) -> str:
    day = (
        f"{build_date.value[:4]}-{build_date.value[4:6]}-{build_date.value[6:]}"
    )
    region_stem = region.value.rsplit("/", 1)[-1]
    if source.vendor == "local":
        return f"local-{source.revision_stem or region.slug}-{day}"
    if role is Role.RASTER_BAKE:
        stem = source.catalog_revision_stem or region_stem
        return f"geofabrik-{stem}-{day}"
    return f"geofabrik-{region_stem}-{day}"
