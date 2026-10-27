from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    build_planner,
    build_orchestration_planner,
    catalog_service,
    catalog_snapshot_service,
    doctor_query,
    artifact_query,
    artifact_file_verifier,
    attribution_writer_service,
    sha512_sidecar_writer_service,
    repository_root,
    workspace_initializer,
    region_skeleton_service,
    yaml_json_transcoder,
    checksum_manifest_writer,
    region_fetch_service,
    tags_filter_service,
    layer_export_service,
    layer_normalization_service,
    tippecanoe_service,
    profile_transform_service,
    island_anchor_service,
    island_water_service,
    admin_line_service,
    place_admin_service,
    style_service,
    sprite_service,
    glyph_service,
    vector_metadata_service,
    vector_manifest_service,
    vector_quality_gate,
    style_quality_gate,
    vector_tile_sampling_gate,
    base_deep_quality_gate,
    vector_build_execution_service,
    vector_build_preparation_service,
    vector_finalization_service,
    raster_planning_service,
    raster_bake_service,
    raster_bake_request_factory,
    raster_finalization_service,
    bundle_service,
)
from huavd_map_build.delivery.north.local.bundle import BundleRequest
from huavd_map_build.production.domain.admin_line import (
    AdminLineExecutionError, AdminLineRequest, MissingAdminLineToolError,
)
from huavd_map_build.production.domain.place_admin import (
    MissingPlaceAdminToolError, PlaceAdminExecutionError, PlaceAdminRequest,
)
from huavd_map_build.production.domain.style import StyleRequest
from huavd_map_build.production.domain.sprite import SpriteRequest
from huavd_map_build.production.domain.glyph import (
    GlyphExecutionError,
    GlyphRequest,
    MissingGlyphToolError,
)
from huavd_map_build.delivery.domain.metadata import (
    MetadataEditError,
    MetadataRequest,
    MetadataVerificationError,
    MissingPmtilesToolError,
)
from huavd_map_build.delivery.domain.manifest import ManifestRequest
from huavd_map_build.production.north.local.vector_finalize import (
    VectorFinalizationRequest,
)
from huavd_map_build.production.north.local.execution import BuildExecutionError
from huavd_map_build.quality.domain.base import BaseDeepQualityError
from huavd_map_build.production.domain.export import (
    ExportExecutionError,
    ExportRequest,
    MissingExportToolError,
)
from huavd_map_build.production.domain.fetch import FetchRequest, FetchToolError
from huavd_map_build.production.domain.normalize import NormalizeRequest
from huavd_map_build.production.domain.tippecanoe import (
    MissingTippecanoeToolError,
    TippecanoeExecutionError,
    TippecanoeRequest,
)
from huavd_map_build.production.domain.profile_transform import ProfileTransformRequest
from huavd_map_build.production.domain.island_anchor import IslandAnchorRequest
from huavd_map_build.production.domain.island_water import IslandWaterRequest
from huavd_map_build.production.domain.tags_filter import (
    MissingTagsFilterToolError,
    TagsFilterExecutionError,
    TagsFilterRequest,
)
from huavd_map_build.production.domain.workspace import WorkspacePlan
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role
from huavd_map_build.shared.kernel.identity import DomainValidationError, SessionId


class LegacySessionInputError(ValueError):
    pass


def _build_failure_exit_code(error: Exception) -> int:
    if isinstance(error, (
        MissingTagsFilterToolError, MissingExportToolError,
        MissingTippecanoeToolError, MissingAdminLineToolError,
        MissingPlaceAdminToolError, MissingPmtilesToolError,
    )):
        return 5
    if isinstance(error, BaseDeepQualityError):
        return 3
    if isinstance(error, ValueError):
        return 2
    if isinstance(error, (
        TagsFilterExecutionError, ExportExecutionError,
        TippecanoeExecutionError, AdminLineExecutionError,
        PlaceAdminExecutionError, MetadataEditError, MetadataVerificationError,
    )):
        return 1
    return 1


def _file_mode(value: str) -> int:
    try:
        mode = int(value, 8)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f"invalid octal mode: {value}") from error
    if mode < 0 or mode > 0o777:
        raise argparse.ArgumentTypeError(f"invalid octal mode: {value}")
    return mode


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="huavd-map-build")
    commands = parser.add_subparsers(dest="context", required=True)

    catalog = commands.add_parser("catalog", help="query and validate map catalog")
    catalog_commands = catalog.add_subparsers(dest="command", required=True)
    catalog_commands.add_parser("validate", help="validate the complete region catalog")
    catalog_commands.add_parser("list", help="list configured region ids")
    snapshot = catalog_commands.add_parser(
        "snapshot", help="write the derived region catalog snapshot"
    )
    snapshot.add_argument("--config", type=Path)
    snapshot.add_argument("--output", type=Path)
    skeleton = catalog_commands.add_parser(
        "generate-skeletons", help="generate region skeleton configuration"
    )
    skeleton.add_argument("--iso3166-2-csv", required=True)
    skeleton.add_argument("--existing-config", type=Path)
    skeleton.add_argument("--output", type=Path)
    yaml_json = catalog_commands.add_parser(
        "yaml-to-json", help="atomically transcode a YAML document to JSON"
    )
    yaml_json.add_argument("--source", required=True)
    yaml_json.add_argument("--output", required=True)
    basename = catalog_commands.add_parser(
        "pbf-basename", help="resolve the configured manual-download PBF basename"
    )
    basename.add_argument("region")
    region = catalog_commands.add_parser(
        "region", help="resolve inherited HUAVD settings for a region"
    )
    region.add_argument("region")
    region.add_argument("--role", default="base")
    region.add_argument("--yyyymmdd", required=True)
    tippecanoe = catalog_commands.add_parser(
        "tippecanoe", help="resolve effective Tippecanoe settings"
    )
    tippecanoe.add_argument("region")
    tippecanoe.add_argument("--role", default="base")
    bake = catalog_commands.add_parser(
        "raster-bake", help="resolve effective raster bake settings"
    )
    bake.add_argument("region")
    vector_layers = catalog_commands.add_parser(
        "vector-layers", help="resolve effective vector layer metadata"
    )
    vector_layers.add_argument("region")
    vector_layers.add_argument("--role", default="base")
    vector_layers.add_argument("--tile-max", type=int)

    build = commands.add_parser("build", help="map production commands")
    build_commands = build.add_subparsers(dest="command", required=True)
    plan = build_commands.add_parser("plan", help="create a side-effect-free build plan")
    plan.add_argument("--region", required=True)
    plan.add_argument("--yyyymmdd", required=True)
    plan.add_argument("--role", default="both")
    plan.add_argument("--workdir", default="/tmp/huavd-map-build")
    plan.add_argument("--input", type=Path)
    execution_plan = build_commands.add_parser(
        "execution-plan", help="resolve the ordered build stage plan"
    )
    execution_plan.add_argument("--region", required=True)
    execution_plan.add_argument("--yyyymmdd", required=True)
    execution_plan.add_argument("--role", default="both")
    execution_plan.add_argument("--workdir", default="/tmp/huavd-map-build")
    execution_plan.add_argument("--input", type=Path)
    execution_plan.add_argument("--glyph", choices=["0", "1"], default="0")
    execution_plan.add_argument("--force-building", action="store_true")
    raster_plan = build_commands.add_parser(
        "raster-plan", help="estimate raster tile coverage and budget status without rendering"
    )
    raster_plan.add_argument("--region", required=True)
    raster_plan.add_argument("--yyyymmdd", required=True)
    raster_plan.add_argument("--workdir", default="/tmp/huavd-map-build")
    raster_plan.add_argument("--bbox")
    raster_plan.add_argument("--min-zoom", type=int)
    raster_plan.add_argument("--max-zoom", type=int)
    raster_plan.add_argument("--max-tiles", type=int)
    raster_bake = build_commands.add_parser(
        "raster-bake", help="build an unpublished raster PMTiles candidate"
    )
    raster_bake.add_argument("--region", required=True)
    raster_bake.add_argument("--yyyymmdd", required=True)
    raster_bake.add_argument("--workdir", default="/tmp/huavd-map-build")
    raster_bake.add_argument("--bbox")
    raster_bake.add_argument("--min-zoom", type=int)
    raster_bake.add_argument("--max-zoom", type=int)
    raster_bake.add_argument("--max-tiles", type=int)
    raster_bake.add_argument(
        "--batch-tiles", type=int,
        help="render the missing queue in serial batches of this size; the total budget is unchanged",
    )
    raster_bake.add_argument(
        "--renderer-engine", choices=["mbgl-renderer", "maplibre-native", "maplibre-native-headless"],
        default=None,
    )
    raster_bake.add_argument("--renderer-command", help="renderer executable; defaults to the selected engine's command")
    raster_bake.add_argument("--sample", action="append", default=[], metavar="LAYER,LON,LAT",
                             help="known feature at highest output zoom; repeat for content preflight and preview")
    raster_bake.add_argument("--jobs", type=int)
    raster_bake.add_argument("--retries", type=int)
    raster_bake.add_argument("--timeout-seconds", type=int)
    raster_bake.add_argument(
        "--display-mode", choices=["managed-xvfb", "external-x11", "headless"]
    )
    raster_bake.add_argument("--extract-pmtiles", action=argparse.BooleanOptionalAction)
    raster_bake.add_argument(
        "--publish", action=argparse.BooleanOptionalAction, default=True,
        help="finalize and publish the verified raster artifact (default: true)",
    )
    execute_base = build_commands.add_parser(
        "execute-base",
        help="run the Python base pipeline as a shadow production entrypoint",
    )
    execute_base.add_argument("--region", required=True)
    execute_base.add_argument("--yyyymmdd", required=True)
    execute_base.add_argument("--workdir", default="/tmp/huavd-map-build")
    execute_base.add_argument("--input", type=Path)
    execute_base.add_argument("--force", action="store_true")
    execute_base.add_argument("--glyph", choices=["0", "1"], default="0")
    execute_vector = build_commands.add_parser(
        "execute-vector", help="run one Python vector-role production pipeline"
    )
    execute_vector.add_argument("--region", required=True)
    execute_vector.add_argument("--yyyymmdd", required=True)
    execute_vector.add_argument(
        "--role", choices=["base", "building", "both"], required=True
    )
    execute_vector.add_argument("--workdir", default="/tmp/huavd-map-build")
    execute_vector.add_argument("--input", type=Path)
    execute_vector.add_argument("--force", action="store_true")
    execute_vector.add_argument("--force-building", action="store_true")
    execute_vector.add_argument("--glyph", choices=["0", "1"], default="0")
    fetch = build_commands.add_parser("fetch", help="download and verify a region PBF")
    fetch.add_argument("--region", required=True)
    fetch.add_argument("--workdir", default="/tmp/huavd-map-build")
    fetch.add_argument("--limit-rate", default="10m")
    tags_filter = build_commands.add_parser(
        "tags-filter", help="filter a source PBF into configured layers"
    )
    tags_filter.add_argument("--input", required=True)
    tags_filter.add_argument("--region", required=True)
    tags_filter.add_argument("--yyyymmdd", required=True)
    tags_filter.add_argument("--session")
    tags_filter.add_argument("--workdir", default="/tmp/huavd-map-build")
    tags_filter.add_argument("--layers", default="all")
    export = build_commands.add_parser(
        "export", help="export filtered PBF layers as GeoJSONSeq"
    )
    export.add_argument("--region", required=True)
    export.add_argument("--yyyymmdd", required=True)
    export.add_argument("--session")
    export.add_argument("--workdir", default="/tmp/huavd-map-build")
    export.add_argument("--layers", default="all")
    normalize = build_commands.add_parser(
        "normalize", help="normalize exported GeoJSONSeq layers"
    )
    normalize.add_argument("--region", required=True)
    normalize.add_argument("--yyyymmdd", required=True)
    normalize.add_argument("--session")
    normalize.add_argument("--workdir", default="/tmp/huavd-map-build")
    normalize.add_argument("--layers", default="all")
    tile = build_commands.add_parser(
        "tippecanoe", help="build vector PMTiles from normalized layers"
    )
    tile.add_argument("--region", required=True)
    tile.add_argument("--yyyymmdd", required=True)
    tile.add_argument("--session")
    tile.add_argument("--role", choices=["base", "building"], required=True)
    tile.add_argument("--workdir", default="/tmp/huavd-map-build")
    profile = build_commands.add_parser(
        "profile-transform", help="apply an effective low-zoom build profile"
    )
    profile.add_argument("--region", required=True)
    profile.add_argument("--yyyymmdd", required=True)
    profile.add_argument("--session")
    profile.add_argument("--workdir", default="/tmp/huavd-map-build")
    profile.add_argument("--layers", required=True)
    anchor = build_commands.add_parser(
        "island-anchor", help="append one label anchor per island polygon"
    )
    anchor.add_argument("--region", required=True)
    anchor.add_argument("--yyyymmdd", required=True)
    anchor.add_argument("--session")
    anchor.add_argument("--workdir", default="/tmp/huavd-map-build")
    water_flag = build_commands.add_parser(
        "island-water-flag", help="mark island polygons enclosed by water"
    )
    water_flag.add_argument("--region", required=True)
    water_flag.add_argument("--yyyymmdd", required=True)
    water_flag.add_argument("--session")
    water_flag.add_argument("--workdir", default="/tmp/huavd-map-build")
    admin_line = build_commands.add_parser(
        "admin-line-tier", help="assign administrative line hierarchy tiers"
    )
    admin_line.add_argument("--region", default="china/guangxi")
    admin_line.add_argument("--overview")
    admin_line.add_argument("--yyyymmdd", required=True)
    admin_line.add_argument("--session")
    admin_line.add_argument("--workdir", default="/tmp/huavd-map-build")
    admin_line.add_argument("--input")
    admin_line.add_argument("--filtered-pbf")
    place_admin = build_commands.add_parser(
        "place-admin-enrich", help="enrich place labels from administrative relations"
    )
    place_admin.add_argument("--input", required=True)
    place_admin.add_argument("--region", required=True)
    place_admin.add_argument("--yyyymmdd", required=True)
    place_admin.add_argument("--session")
    place_admin.add_argument("--workdir", default="/tmp/huavd-map-build")
    style = build_commands.add_parser("style", help="compile offline MapLibre styles")
    style.add_argument("--region", required=True)
    style.add_argument("--yyyymmdd", required=True)
    style.add_argument("--session")
    style.add_argument("--workdir", default="/tmp/huavd-map-build")
    style.add_argument("--locale")
    style.add_argument("--pmtiles-url")
    sprite = build_commands.add_parser("sprite", help="build offline map sprites")
    sprite.add_argument("--region", required=True)
    sprite.add_argument("--yyyymmdd", required=True)
    sprite.add_argument("--session")
    sprite.add_argument("--workdir", default="/tmp/huavd-map-build")
    sprite.add_argument("--force", action="store_true")
    glyph = build_commands.add_parser("glyph", help="build offline map glyphs")
    glyph.add_argument("--region", required=True)
    glyph.add_argument("--yyyymmdd", required=True)
    glyph.add_argument("--session")
    glyph.add_argument("--workdir", default="/tmp/huavd-map-build")
    glyph.add_argument("--locales", default="all")
    glyph.add_argument("--force", action="store_true")

    doctor = commands.add_parser("doctor", help="probe core tools and validate the catalog")
    doctor.add_argument("--strict", action="store_true", help="fail if any required tool is unavailable")

    quality = commands.add_parser("quality", help="artifact semantic quality gates")
    quality_commands = quality.add_subparsers(dest="command", required=True)
    vector_quality = quality_commands.add_parser(
        "vector", help="verify vector PMTiles metadata and manifest semantics"
    )
    vector_quality.add_argument("--region", required=True)
    vector_quality.add_argument("--yyyymmdd", required=True)
    vector_quality.add_argument("--role", choices=["base", "building"], required=True)
    vector_quality.add_argument("--workdir", default="/tmp/huavd-map-build")
    style_quality = quality_commands.add_parser(
        "style", help="verify vector style and glyph/sprite resource closure"
    )
    style_quality.add_argument("--region", required=True)
    style_quality.add_argument("--yyyymmdd", required=True)
    style_quality.add_argument("--workdir", default="/tmp/huavd-map-build")
    tile_quality = quality_commands.add_parser(
        "tile", help="sample decoded vector tiles using staged feature locations"
    )
    tile_quality.add_argument("--region", required=True)
    tile_quality.add_argument("--yyyymmdd", required=True)
    tile_quality.add_argument("--workdir", default="/tmp/huavd-map-build")
    base_quality = quality_commands.add_parser(
        "base", help="run combined staged and decoded-tile base quality gates"
    )
    base_quality.add_argument("--region", required=True)
    base_quality.add_argument("--yyyymmdd", required=True)
    base_quality.add_argument("--workdir", default="/tmp/huavd-map-build")
    release_quality = quality_commands.add_parser(
        "release", help="verify all vector artifacts selected for a release"
    )
    release_quality.add_argument("--region", required=True)
    release_quality.add_argument("--yyyymmdd", required=True)
    release_quality.add_argument("--role", choices=["base", "building", "both"], default="both")
    release_quality.add_argument("--workdir", default="/tmp/huavd-map-build")

    workspace = commands.add_parser("workspace", help="workspace commands")
    workspace_commands = workspace.add_subparsers(dest="command", required=True)
    initialize = workspace_commands.add_parser(
        "init", help="initialize the map build workspace"
    )
    initialize.add_argument("--workdir", default="/tmp/huavd-map-build")
    initialize.add_argument("--session", required=True)
    initialize.add_argument("--directory-mode", type=_file_mode, default=0o750)
    initialize.add_argument(
        "--config-directory-mode", type=_file_mode, default=0o755
    )
    initialize.add_argument("--file-mode", type=_file_mode, default=0o644)
    initialize.add_argument("--copy-config", action="store_true")

    artifact = commands.add_parser("artifact", help="artifact delivery queries")
    artifact_commands = artifact.add_subparsers(dest="command", required=True)
    paths = artifact_commands.add_parser("paths", help="resolve artifact paths")
    paths.add_argument("--region", required=True)
    paths.add_argument("--yyyymmdd", required=True)
    paths.add_argument("--role", choices=[role.value for role in Role], required=True)
    paths.add_argument("--workdir", default="/tmp/huavd-map-build")
    digest = artifact_commands.add_parser("sha512", help="calculate a file SHA-512")
    digest.add_argument("path")
    checksum = artifact_commands.add_parser("checksum", help="calculate a file digest")
    checksum.add_argument("--algorithm", choices=["md5", "sha256", "sha512"], required=True)
    checksum.add_argument("path")
    manifest = artifact_commands.add_parser(
        "write-checksum-manifest", help="write a sorted checksum manifest"
    )
    manifest.add_argument("--algorithm", choices=["md5", "sha256", "sha512"], required=True)
    manifest.add_argument("--root", required=True)
    manifest.add_argument("--output-name", required=True)
    manifest.add_argument("--exclude-name", action="append", default=[])
    manifest.add_argument("--exclude-suffix", action="append", default=[])
    artifact_commands.add_parser(
        "sha512-stdin", help="calculate SHA-512 from standard input"
    )
    write_digest = artifact_commands.add_parser(
        "write-sha512", help="atomically write a sha512sum-compatible sidecar"
    )
    write_digest.add_argument("path")
    verify_files = artifact_commands.add_parser(
        "verify-files", help="verify artifact files and SHA-512 sidecars"
    )
    verify_files.add_argument("--region", required=True)
    verify_files.add_argument("--yyyymmdd", required=True)
    verify_files.add_argument("--role", choices=[role.value for role in Role], required=True)
    verify_files.add_argument("--workdir", default="/tmp/huavd-map-build")
    verify_files.add_argument("--consumer-closure", action="store_true")
    verify_files.add_argument("--ready-marker", action="store_true")
    attribution = artifact_commands.add_parser(
        "attribution", help="render the canonical OSM attribution document"
    )
    attribution.add_argument("--region", required=True)
    attribution.add_argument("--yyyymmdd", required=True)
    attribution.add_argument("--role", choices=["base", "building", "raster_bake"], default="base")
    attribution.add_argument("--workdir", default="/tmp/huavd-map-build")
    attribution.add_argument("--session")
    write_attribution = artifact_commands.add_parser(
        "write-attribution", help="atomically write the canonical attribution file"
    )
    write_attribution.add_argument("--region", required=True)
    write_attribution.add_argument("--yyyymmdd", required=True)
    write_attribution.add_argument(
        "--role", choices=["base", "building", "raster_bake"], required=True
    )
    write_attribution.add_argument("--workdir", default="/tmp/huavd-map-build")
    write_attribution.add_argument("--session")
    write_metadata = artifact_commands.add_parser(
        "write-vector-metadata", help="write base/building PMTiles metadata"
    )
    write_metadata.add_argument("--region", required=True)
    write_metadata.add_argument("--yyyymmdd", required=True)
    write_metadata.add_argument("--session")
    write_metadata.add_argument("--role", choices=["base", "building"], required=True)
    write_metadata.add_argument("--workdir", default="/tmp/huavd-map-build")
    write_metadata.add_argument("--pmtiles")
    write_manifest = artifact_commands.add_parser(
        "write-vector-manifest", help="write base/building artifact manifest"
    )
    write_manifest.add_argument("--region", required=True)
    write_manifest.add_argument("--yyyymmdd", required=True)
    write_manifest.add_argument("--session")
    write_manifest.add_argument("--role", choices=["base", "building"], required=True)
    write_manifest.add_argument("--workdir", default="/tmp/huavd-map-build")
    write_manifest.add_argument("--bundle-id")
    write_manifest.add_argument("--activation", default="manual")
    finalize_vector = artifact_commands.add_parser(
        "finalize-vector", help="write and verify vector delivery documents"
    )
    finalize_vector.add_argument("--region", required=True)
    finalize_vector.add_argument("--yyyymmdd", required=True)
    finalize_vector.add_argument("--session")
    finalize_vector.add_argument("--role", choices=["base", "building"], required=True)
    finalize_vector.add_argument("--workdir", default="/tmp/huavd-map-build")
    finalize_vector.add_argument("--bundle-id")
    finalize_vector.add_argument("--activation", default="manual")
    bundle = artifact_commands.add_parser(
        "pack", help="build a consumer-installable offline map bundle"
    )
    bundle.add_argument("--region", required=True)
    bundle.add_argument("--yyyymmdd", required=True)
    bundle.add_argument("--session")
    bundle.add_argument(
        "--role", choices=["base", "building", "both", "raster_bake", "base_raster", "both_raster"],
        default="both",
    )
    bundle.add_argument("--format", choices=["tar", "zip", "both"], default="both")
    bundle.add_argument("--workdir", default="/tmp/huavd-map-build")
    return parser


def run(arguments: list[str] | None = None) -> int:
    args = _parser().parse_args(arguments)

    if args.context == "doctor":
        root = repository_root()
        report = doctor_query(root).execute()
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if (report.healthy if args.strict else report.passed) else 3
    if args.context == "quality" and args.command == "vector":
        report = vector_quality_gate(repository_root()).verify(
            region=RegionId(args.region), build_date=BuildDate(args.yyyymmdd),
            role=Role(args.role), workdir=args.workdir,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    if args.context == "quality" and args.command == "release":
        region, build_date = RegionId(args.region), BuildDate(args.yyyymmdd)
        selected = (Role.BASE, Role.BUILDING) if args.role == "both" else (Role(args.role),)
        reports: list[dict[str, object]] = []
        passed = True
        for role in selected:
            paths = artifact_query().paths(
                region=region,
                build_date=build_date,
                role=role,
                workdir=args.workdir,
            )
            if role is Role.BUILDING and args.role == "both" and not Path(paths.pmtiles).is_file():
                reports.append({"role": role.value, "status": "skipped", "reason": "optional artifact is absent"})
                continue
            quality = vector_quality_gate(repository_root()).verify(
                region=region, build_date=build_date, role=role, workdir=args.workdir
            )
            files = artifact_file_verifier().verify(paths)
            role_passed = quality.passed and files.passed
            deep = None
            if role is Role.BASE and role_passed:
                build = build_planner(repository_root()).plan(
                    region=region, build_date=build_date, role="base", workdir=Path(args.workdir),
                    input_path=Path(args.workdir) / "staging" / paths.identity.session.value / "source.osm.pbf",
                )
                deep = base_deep_quality_gate(repository_root()).inspect(build)
                role_passed = deep.passed
            passed = passed and role_passed
            reports.append({
                "role": role.value, "status": "passed" if role_passed else "failed",
                "quality": quality.as_dict(), "files": files.as_dict(),
                "deep": deep.as_dict() if deep is not None else None,
            })
        print(json.dumps({
            "schema_version": 1, "status": "passed" if passed else "failed",
            "region": region.value, "yyyymmdd": build_date.value, "roles": reports,
        }, ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if passed else 3
    if args.context == "quality" and args.command == "style":
        report = style_quality_gate(repository_root()).verify(
            region=RegionId(args.region), build_date=BuildDate(args.yyyymmdd),
            workdir=args.workdir,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    if args.context == "quality" and args.command == "tile":
        report = vector_tile_sampling_gate().verify(
            region=RegionId(args.region), build_date=BuildDate(args.yyyymmdd),
            workdir=args.workdir,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    if args.context == "quality" and args.command == "base":
        build = build_planner(repository_root()).plan(
            region=RegionId(args.region), build_date=BuildDate(args.yyyymmdd),
            role="base", workdir=Path(args.workdir),
            input_path=Path(args.workdir) / "staging" / f"{RegionId(args.region).slug}-{args.yyyymmdd}" / "source.osm.pbf",
        )
        report = base_deep_quality_gate(repository_root()).inspect(build)
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    if args.context == "workspace" and args.command == "init":
        try:
            session = SessionId(args.session)
        except DomainValidationError as error:
            raise LegacySessionInputError(
                f"invalid HUAVD_MAP_BUILD_SESSION: {args.session}\n"
                "expected {region-slug}-{yyyymmdd}, e.g. china-guangxi-20260818"
            ) from error
        result = workspace_initializer().initialize(
            WorkspacePlan(
                root=args.workdir,
                session=session,
                directory_mode=args.directory_mode,
                config_directory_mode=args.config_directory_mode,
                config_file_mode=args.file_mode,
                copy_config=args.copy_config,
            )
        )
        print(f"huavd-map-build workdir initialized: {result.root}")
        print(f"session: {result.session}")
        return 0
    if args.context == "artifact" and args.command == "paths":
        paths = artifact_query().paths(
            region=RegionId(args.region),
            build_date=BuildDate(args.yyyymmdd),
            role=Role(args.role),
            workdir=args.workdir,
        )
        print(json.dumps(paths.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.context == "artifact" and args.command == "sha512":
        print(artifact_query().sha512(args.path))
        return 0
    if args.context == "artifact" and args.command == "checksum":
        print(artifact_query().checksum(args.path, args.algorithm))
        return 0
    if args.context == "artifact" and args.command == "write-checksum-manifest":
        manifest = checksum_manifest_writer().write(
            root=args.root,
            output_name=args.output_name,
            algorithm=args.algorithm,
            excluded_names=tuple(args.exclude_name),
            excluded_suffixes=tuple(args.exclude_suffix),
        )
        print(len(manifest.entries))
        return 0
    if args.context == "artifact" and args.command == "sha512-stdin":
        chunks = iter(lambda: sys.stdin.buffer.read(1024 * 1024), b"")
        print(artifact_query().sha512_chunks(chunks))
        return 0
    if args.context == "artifact" and args.command == "write-sha512":
        output = sha512_sidecar_writer_service().write(args.path)
        print(output)
        return 0
    if args.context == "artifact" and args.command == "verify-files":
        paths = artifact_query().paths(
            region=RegionId(args.region),
            build_date=BuildDate(args.yyyymmdd),
            role=Role(args.role),
            workdir=args.workdir,
        )
        report = artifact_file_verifier().verify(
            paths,
            require_consumer_closure=args.consumer_closure,
            require_ready_marker=args.ready_marker,
        )
        print(json.dumps(report.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if report.passed else 3
    if args.context == "artifact" and args.command in ("attribution", "write-attribution"):
        from huavd_map_build.delivery.domain.attribution import AttributionDocument
        from huavd_map_build.delivery.north.local.source import read_manifest_source

        region = RegionId(args.region)
        catalog_service(repository_root()).region(region)
        if args.session:
            SessionId(args.session)
        paths = artifact_query().paths(
            region=region,
            build_date=BuildDate(args.yyyymmdd),
            role=Role(args.role),
            workdir=args.workdir,
        )
        source = read_manifest_source(paths.manifest)
        document = AttributionDocument.osm(source.vendor, source.url)
        if args.command == "attribution":
            print(json.dumps(document.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        output = attribution_writer_service().write(paths, document)
        print(
            json.dumps(
                {"schema_version": "1", "status": "written", "path": output},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0
    if args.context == "artifact" and args.command == "write-vector-metadata":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        output = vector_metadata_service(repository_root()).run(MetadataRequest(
            region, build_date, session, Role(args.role), args.workdir, args.pmtiles
        ))
        print(output)
        return 0
    if args.context == "artifact" and args.command == "write-vector-manifest":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        output = vector_manifest_service(repository_root()).run(ManifestRequest(
            region, build_date, session, Role(args.role), args.workdir,
            args.bundle_id, args.activation,
        ))
        print(output)
        return 0
    if args.context == "artifact" and args.command == "finalize-vector":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        result = vector_finalization_service(repository_root()).run(
            VectorFinalizationRequest(
                region, build_date, session, Role(args.role), args.workdir,
                args.bundle_id, args.activation,
            )
        )
        print(json.dumps(result.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0 if result.passed else 3
    if args.context == "artifact" and args.command == "pack":
        region, build_date = RegionId(args.region), BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        outputs = Path(args.workdir) / "outputs"
        if not (outputs / f"{session.value}.glyphs").is_dir():
            glyph_service(repository_root()).run(
                GlyphRequest(region, session, args.workdir, force=True)
            )
        if not (outputs / f"{session.value}.sprite").is_dir():
            sprite_service(repository_root()).run(
                SpriteRequest(region, session, args.workdir, force=True)
            )
        if (
            not (outputs / f"{session.value}.style.json").is_file()
            or not (outputs / f"{session.value}.style-raster.json").is_file()
        ):
            style_service(repository_root()).run(StyleRequest(region, session, args.workdir))
        result = bundle_service().run(BundleRequest(
            region, build_date, session, args.role, args.workdir, args.format
        ))
        print(json.dumps(result, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    root = repository_root()
    catalog = catalog_service(root)

    if args.context == "catalog" and args.command == "validate":
        summary = catalog.validate()
        configuration_summary = build_configuration_service(root).validate()
        print(json.dumps({
            "schema_version": summary.schema_version,
            "region_count": summary.region_count,
            "layer_count": configuration_summary.layer_count,
            "tier_profile_count": configuration_summary.tier_profile_count,
            "configuration_schema_versions": dict(
                configuration_summary.schema_versions
            ),
            "status": "valid",
        }, ensure_ascii=True, sort_keys=True))
        return 0
    if args.context == "catalog" and args.command == "list":
        for region in catalog.list_regions():
            print(region.id.value)
        return 0
    if args.context == "catalog" and args.command == "snapshot":
        root = repository_root()
        config = args.config or root / "config/regions.yaml"
        output = args.output or root / "config/derived/catalog.json"
        catalog_snapshot_service(config).write(str(output))
        print(f"wrote {output}")
        return 0
    if args.context == "catalog" and args.command == "generate-skeletons":
        root = repository_root()
        existing = args.existing_config or root / "config/regions.yaml"
        service = region_skeleton_service()
        if args.output is None:
            print(service.render_new(args.iso3166_2_csv, str(existing)), end="")
        else:
            service.write(args.iso3166_2_csv, str(existing), str(args.output))
            print(f"wrote {args.output}")
        return 0
    if args.context == "catalog" and args.command == "yaml-to-json":
        yaml_json_transcoder().transcode(args.source, args.output)
        return 0
    if args.context == "catalog" and args.command == "pbf-basename":
        print(catalog.pbf_basename(RegionId(args.region)))
        return 0
    if args.context == "catalog" and args.command == "region":
        BuildDate(args.yyyymmdd)
        print(
            json.dumps(
                catalog.region_settings(
                    RegionId(args.region), args.role, args.yyyymmdd
                ),
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 0
    if args.context == "catalog" and args.command in {
        "tippecanoe",
        "raster-bake",
        "vector-layers",
    }:
        configuration = build_configuration_service(root)
        if args.command == "tippecanoe":
            result = configuration.tippecanoe(args.region, args.role)
        elif args.command == "raster-bake":
            result = configuration.raster_bake(args.region)
        else:
            result = configuration.vector_layers(args.region, args.role, args.tile_max)
        print(json.dumps(result, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
        return 0
    if args.context == "build" and args.command == "plan":
        plan = build_planner(root).plan(
            region=RegionId(args.region),
            build_date=BuildDate(args.yyyymmdd),
            role=args.role,
            workdir=Path(args.workdir),
            input_path=args.input,
        )
        print(json.dumps(plan.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.context == "build" and args.command == "execution-plan":
        plan = build_planner(root).plan(
            region=RegionId(args.region),
            build_date=BuildDate(args.yyyymmdd),
            role=args.role,
            workdir=Path(args.workdir),
            input_path=args.input,
        )
        execution = build_orchestration_planner(root).plan(
            plan, args.glyph == "1", args.force_building
        )
        print(json.dumps(
            execution.as_dict(), ensure_ascii=True, indent=2, sort_keys=True
        ))
        return 0
    if args.context == "build" and args.command == "raster-plan":
        bounds = None
        if args.bbox:
            from huavd_map_build.production.domain.raster import RasterBounds

            parts = args.bbox.split(",")
            if len(parts) != 4:
                raise ValueError("--bbox must contain west,south,east,north")
            bounds = RasterBounds(*(float(value) for value in parts))
        from huavd_map_build.production.north.local.raster import RasterPlanRequest

        plan = raster_planning_service(root).estimate(RasterPlanRequest(
            RegionId(args.region), BuildDate(args.yyyymmdd), args.workdir,
            bounds, args.min_zoom, args.max_zoom, args.max_tiles,
        ))
        from huavd_map_build.production.domain.raster import validate_raster_batch_tiles

        batch_tiles = validate_raster_batch_tiles(
            build_configuration_service(root).raster_bake(args.region).get("batch_tiles")
        )
        document = plan.as_dict()
        document["within_limit"] = plan.within_limit
        document["budget_source"] = plan.max_tiles_source
        document["batch_tiles"] = batch_tiles
        document["estimated_batches"] = (
            None if batch_tiles is None
            else (plan.tile_count + batch_tiles - 1) // batch_tiles
        )
        print(json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.context == "build" and args.command == "raster-bake":
        from huavd_map_build.delivery.south.adapter.process.tool_versions import (
            ProcessToolVersionReader,
        )
        from huavd_map_build.production.domain.raster import RasterBounds
        from huavd_map_build.production.north.local.raster import RasterPlanRequest
        from huavd_map_build.production.north.local.raster_request import (
            RasterBakeOverrides,
        )

        bounds = None
        if args.bbox:
            parts = args.bbox.split(",")
            if len(parts) != 4:
                raise ValueError("--bbox must contain west,south,east,north")
            bounds = RasterBounds(*(float(value) for value in parts))
        region, build_date = RegionId(args.region), BuildDate(args.yyyymmdd)
        plan = raster_planning_service(root).plan(RasterPlanRequest(
            region, build_date, args.workdir, bounds, args.min_zoom,
            args.max_zoom, args.max_tiles,
        ))
        bake_settings = build_configuration_service(root).raster_bake(args.region)
        from huavd_map_build.production.domain.raster import validate_raster_batch_tiles

        batch_tiles = validate_raster_batch_tiles(
            args.batch_tiles if args.batch_tiles is not None
            else bake_settings.get("batch_tiles")
        )
        if plan.max_tiles_source == "auto-headroom":
            print(
                f"warning: raster plan {plan.tile_count} exceeds configured "
                f"max_tiles {plan.configured_max_tiles}; "
                f"using automatic headroom budget {plan.max_tiles}",
                file=sys.stderr,
            )
        print(
            f"raster plan: tiles={plan.tile_count} max_tiles={plan.max_tiles} "
            f"configured_max_tiles={plan.configured_max_tiles} "
            f"budget_source={plan.max_tiles_source} batch_tiles={batch_tiles}",
            file=sys.stderr,
        )
        args.renderer_engine = args.renderer_engine or bake_settings.get("renderer_engine", "maplibre-native-headless")
        if args.renderer_command is None:
            if args.renderer_engine == "maplibre-native-headless":
                from huavd_map_build.production.south.adapter.process.native_tools import resolve_renderer

                args.renderer_command = resolve_renderer()
            else:
                args.renderer_command = "mbgl-render"
        if args.renderer_engine == "maplibre-native-headless":
            from huavd_map_build.production.south.adapter.process.raster_native import (
                native_renderer_identity,
            )

            renderer_identity = native_renderer_identity(args.renderer_command)
        else:
            renderer_identity = ProcessToolVersionReader().versions(
                (args.renderer_command,)
            )[args.renderer_command]
        from huavd_map_build.production.domain.raster import RasterContentSample

        samples = []
        for value in args.sample:
            parts = value.split(",")
            if len(parts) != 3:
                raise ValueError("sample requires LAYER,LON,LAT")
            samples.append(RasterContentSample(parts[0], float(parts[1]), float(parts[2])))
        request = raster_bake_request_factory(root).create(
            region, build_date, args.workdir, plan,
            RasterBakeOverrides(
                args.renderer_engine, args.renderer_command, renderer_identity,
                args.jobs, args.retries, args.timeout_seconds,
                args.extract_pmtiles, args.display_mode, tuple(samples),
                args.batch_tiles,
            ),
        )
        result = raster_bake_service().bake(request)
        document = result.as_dict()
        document["budget"] = {
            "source": plan.max_tiles_source,
            "max_tiles": plan.max_tiles,
            "configured_max_tiles": plan.configured_max_tiles,
        }
        document["candidate_pmtiles"] = request.pmtiles_path
        from huavd_map_build.production.south.adapter.process.raster_preview import write_preview

        document["inspection"] = write_preview(
            Path(args.workdir) / "cache/bake" / f"{region.slug}-{build_date.value}", plan, tuple(samples)
        )
        if args.publish:
            from huavd_map_build.production.north.local.raster_finalize import (
                RasterFinalizationRequest,
            )

            finalized = raster_finalization_service(root).run(
                RasterFinalizationRequest(
                    region, build_date, SessionId.for_build(region, build_date),
                    args.workdir,
                    request.pmtiles_path, plan.tile_count,
                    request.render_settings.tile_size,
                )
            )
            document["finalization"] = finalized.as_dict()
            document["published"] = finalized.published
            print(json.dumps(
                document, ensure_ascii=True, indent=2, sort_keys=True
            ))
            return 0 if finalized.passed else 4
        document["published"] = False
        print(json.dumps(document, ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.context == "build" and args.command in ("execute-base", "execute-vector"):
        role = "base" if args.command == "execute-base" else args.role
        plan = build_planner(root).plan(
            region=RegionId(args.region),
            build_date=BuildDate(args.yyyymmdd),
            role=role,
            workdir=Path(args.workdir),
            input_path=args.input,
        )
        execution = build_orchestration_planner(root).plan(
            plan, glyph=args.glyph == "1",
            force_building=(
                args.force_building if args.command == "execute-vector" else False
            ),
        )
        preparation = vector_build_preparation_service()
        for effective_role in execution.build.roles:
            paths = artifact_query().paths(
                region=execution.build.region,
                build_date=execution.build.build_date,
                role=effective_role,
                workdir=execution.build.workdir,
            )
            preparation.prepare(paths, force=args.force)
        try:
            def report_stage(status: str, stage: str, index: int, total: int) -> None:
                print(
                    f"build {status.upper()} stage={index}/{total} id={stage}",
                    file=sys.stderr, flush=True,
                )

            job = vector_build_execution_service(root, report_stage).run(execution)
        except BuildExecutionError as error:
            document = error.job.as_dict()
            if isinstance(error.cause, BaseDeepQualityError):
                document["quality"] = error.cause.report.as_dict()
            print(json.dumps(
                document, ensure_ascii=True, indent=2, sort_keys=True
            ))
            return _build_failure_exit_code(error.cause)
        print(json.dumps(job.as_dict(), ensure_ascii=True, indent=2, sort_keys=True))
        return 0
    if args.context == "build" and args.command == "fetch":
        output = region_fetch_service(root).fetch(
            FetchRequest(
                region=RegionId(args.region),
                workdir=args.workdir,
                limit_rate=args.limit_rate,
            )
        )
        print(f"{Path(output).name}: OK")
        print(output)
        return 0
    if args.context == "build" and args.command == "tags-filter":
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            RegionId(args.region), build_date
        )
        plan = tags_filter_service(root).run(
            TagsFilterRequest(
                region=RegionId(args.region),
                input_path=args.input,
                workdir=args.workdir,
                layers=args.layers,
            )
        )
        print(plan.cache_directory)
        return 0
    if args.context == "build" and args.command == "export":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        plan = layer_export_service(root).run(
            ExportRequest(region, session, args.workdir, args.layers)
        )
        print(plan.layers_directory)
        return 0
    if args.context == "build" and args.command == "normalize":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        output = layer_normalization_service(root).run(
            NormalizeRequest(region, session, args.workdir, args.layers)
        )
        print(output)
        return 0
    if args.context == "build" and args.command == "tippecanoe":
        region = RegionId(args.region)
        supplied_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, supplied_date
        )
        build_date = BuildDate(session.value[-8:]) if args.session else supplied_date
        plan = tippecanoe_service(root).run(
            TippecanoeRequest(
                region, build_date, session, Role(args.role), args.workdir
            )
        )
        print(plan.output_path)
        return 0
    if args.context == "build" and args.command == "profile-transform":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        result = profile_transform_service(root).run(
            ProfileTransformRequest(region, session, args.workdir, args.layers)
        )
        if result is not None:
            print(result)
        return 0
    if args.context == "build" and args.command == "island-anchor":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        result = island_anchor_service(root).run(
            IslandAnchorRequest(region, session, args.workdir)
        )
        print(result.report_path)
        return 0
    if args.context == "build" and args.command == "island-water-flag":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        result = island_water_service(root).run(
            IslandWaterRequest(region, session, args.workdir)
        )
        print(result.report_path)
        return 0
    if args.context == "build" and args.command == "admin-line-tier":
        build_date = BuildDate(args.yyyymmdd)
        overview = args.overview is not None
        target = args.overview if overview else args.region
        region = RegionId(args.region)
        session = (
            args.session or SessionId.for_build(region, build_date).value
            if overview
            else (
                SessionId(args.session).value
                if args.session
                else SessionId.for_build(region, build_date).value
            )
        )
        report = admin_line_service(root).run(AdminLineRequest(
            target=target, build_date=build_date.value, workdir=args.workdir,
            session=session, overview=overview, input_path=args.input,
            filtered_pbf=args.filtered_pbf,
        ))
        print(report)
        return 0
    if args.context == "build" and args.command == "place-admin-enrich":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        report = place_admin_service(root).run(
            PlaceAdminRequest(region, session, args.workdir, args.input)
        )
        print(report)
        return 0
    if args.context == "build" and args.command == "style":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        for path in style_service(root).run(StyleRequest(
            region, session, args.workdir, args.locale, args.pmtiles_url
        )):
            print(path)
        return 0
    if args.context == "build" and args.command == "sprite":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        paths = sprite_service(root).run(
            SpriteRequest(region, session, args.workdir, args.force)
        )
        print(Path(paths[0]).parent)
        return 0
    if args.context == "build" and args.command == "glyph":
        region = RegionId(args.region)
        build_date = BuildDate(args.yyyymmdd)
        session = SessionId(args.session) if args.session else SessionId.for_build(
            region, build_date
        )
        paths = glyph_service(root).run(
            GlyphRequest(region, session, args.workdir, args.locales, args.force)
        )
        print(Path(paths[-1]).parent)
        return 0
    raise AssertionError("unhandled command")


def main() -> int:
    try:
        return run()
    except LegacySessionInputError as error:
        print(str(error), file=sys.stderr)
        return 64
    except FetchToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except MissingTagsFilterToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except TagsFilterExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingExportToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except ExportExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingTippecanoeToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except TippecanoeExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingAdminLineToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except AdminLineExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingPlaceAdminToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except PlaceAdminExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingGlyphToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except GlyphExecutionError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MissingPmtilesToolError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 5
    except MetadataEditError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except MetadataVerificationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 3
    except (RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
