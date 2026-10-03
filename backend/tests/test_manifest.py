import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    raster_manifest_service,
    repository_root,
)
from huavd_map_build.delivery.domain.manifest import (
    ManifestRequest,
    RasterManifestRequest,
    SourceEvidence,
    compile_raster_manifest,
    compile_vector_manifest,
)
from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.delivery.north.local.manifest import (
    RasterManifestService,
    VectorManifestService,
)
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.south.adapter.filesystem.manifest import (
    FileSystemManifestEvidenceReader,
    JsonManifestWriter,
)
from huavd_map_build.delivery.south.adapter.filesystem.metadata import (
    FileSystemPmtilesHeaderReader,
)
from huavd_map_build.delivery.south.adapter.process.tool_versions import (
    ProcessToolVersionReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


def write_header(
    path: Path, min_zoom: int = 0, max_zoom: int = 15,
    tile_type: int = 1, tile_compression: int = 2, tile_count: int = 0,
) -> None:
    payload = bytearray(127)
    payload[:8] = b"PMTiles\x03"
    payload[97:102] = bytes((2, tile_compression, tile_type, min_zoom, max_zoom))
    struct.pack_into("<Q", payload, 72, tile_count)
    struct.pack_into("<iiii", payload, 102, 100_000_000, 200_000_000,
                     120_000_000, 240_000_000)
    path.write_bytes(payload)


class FixedVersions:
    def versions(self, names: tuple[str, ...]) -> dict[str, str]:
        return {name: f"{name}-fixture" for name in names}


class VectorManifestDomainTest(unittest.TestCase):
    def test_building_contract_uses_role_specific_identity(self) -> None:
        request = ManifestRequest(
            RegionId("china/guangxi"), BuildDate("20261003"),
            SessionId("china-guangxi-20261003"), Role.BUILDING, "/tmp/maps",
        )
        document = compile_vector_manifest(
            request=request,
            header=PmtilesHeader(1, 2, 12, 18, (100, 20, 110, 30)),
            output_path="outputs/map.pmtiles", output_size=4, sha512="a" * 128,
            source_url="https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf",
            evidence=SourceEvidence(None, None, None), tools={}, tippecanoe={},
            vector_layers=["building"], source_id="osm-china-guangxi-building",
            offline_map_id="cn-45-base", package_version="20261003-building",
            style_id="osm-dev", available_locales=("zh-Hans",),
            style_locales=("zh-Hans",), build_id="2026-10-03T00:00:00Z",
        )
        record = document["huavd_record"]
        self.assertEqual("osm-china-guangxi-building", record["source_id"])
        self.assertEqual("building-vector", record["asset_role"])
        self.assertEqual("osm-pbf", record["source_type"])

    def test_raster_contract_records_plan_and_base_lineage(self) -> None:
        request = RasterManifestRequest(
            RegionId("china/guangxi"), BuildDate("20261003"),
            SessionId("china-guangxi-20261003"), "/tmp/maps",
            "/tmp/candidate.pmtiles", "/tmp/candidate.manifest.json", 2, 256,
        )
        document = compile_raster_manifest(
            request=request,
            header=PmtilesHeader(4, 1, 3, 8, (100, 20, 110, 30)),
            output_path="outputs/china-guangxi-20261003.raster_bake.pmtiles",
            output_size=127, sha512="a" * 128, source_url="source",
            evidence=SourceEvidence(None, None, None), tools={},
            source_id="osm-china-guangxi", offline_map_id="cn-45-base",
            package_version="20261003-raster", style_id="osm-dev",
            available_locales=("zh-Hans",), style_locales=("zh-Hans",),
            build_id="2026-10-03T00:00:00Z",
            source_revision="geofabrik-guangxi-2026-10-03",
            base_input={"sha512": "b" * 128},
            plan={"plan_sha512": "c" * 128},
        )
        self.assertEqual([], document["vector_layers"])
        self.assertEqual("raster-baked", document["huavd_record"]["asset_role"])
        self.assertEqual(
            "geofabrik-guangxi-2026-10-03",
            document["huavd_record"]["source_revision"],
        )
        self.assertEqual(2, document["raster_bake"]["tile_count"])
        with self.assertRaisesRegex(ValueError, "WebP"):
            compile_raster_manifest(
                request=request,
                header=PmtilesHeader(1, 2, 3, 8, (100, 20, 110, 30)),
                output_path="output", output_size=1, sha512="a",
                source_url="source", evidence=SourceEvidence(None, None, None),
                tools={}, source_id="source", offline_map_id="id",
                package_version="version", style_id="style",
                available_locales=(), style_locales=(), build_id="now",
                source_revision="revision", base_input={}, plan={},
            )


class ToolVersionReaderTest(unittest.TestCase):
    def test_captures_successful_version_from_stderr(self) -> None:
        result = Mock(returncode=0, stdout="", stderr="tippecanoe v2.79.0\n")
        with patch("shutil.which", return_value="/tools/tippecanoe"), patch(
            "subprocess.run", return_value=result
        ) as run:
            versions = ProcessToolVersionReader().versions(("tippecanoe",))
        self.assertEqual("tippecanoe v2.79.0", versions["tippecanoe"])
        self.assertEqual(
            ["/tools/tippecanoe", "--version"], run.call_args.args[0]
        )


class VectorManifestServiceTest(unittest.TestCase):
    def test_writes_manual_source_evidence_and_output_integrity(self) -> None:
        root = repository_root(Path(__file__))
        service = VectorManifestService(
            catalog_service(root), build_configuration_service(root),
            FileSystemPmtilesHeaderReader(), FileSystemManifestEvidenceReader(),
            FixedVersions(), FileDigestAdapter(), JsonManifestWriter(AtomicFileWriter()),
            lambda: "2026-10-03T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = "china-guangxi-20261003"
            output = workspace / f"outputs/{session}.base.pmtiles"
            output.parent.mkdir()
            write_header(output)
            source = workspace / f"staging/{session}/source.osm.pbf"
            source.parent.mkdir(parents=True)
            manual = workspace / "manual/custom.osm.pbf"
            manual.parent.mkdir()
            manual.write_bytes(b"manual-pbf")
            os.symlink(manual, source)
            md5 = workspace / "mirror/guangxi-latest.osm.pbf.md5"
            md5.parent.mkdir()
            md5.write_text("0123456789abcdef0123456789abcdef  file\n", encoding="ascii")
            manifest = service.run(ManifestRequest(
                RegionId("china/guangxi"), BuildDate("20261003"),
                SessionId(session), Role.BASE, directory,
            ))
            document = json.loads(Path(manifest).read_text(encoding="utf-8"))
            self.assertEqual(len(manual.read_bytes()), document["source"]["size_bytes"])
            self.assertEqual("0123456789abcdef0123456789abcdef", document["source"]["md5"])
            self.assertEqual(
                hashlib.sha512(output.read_bytes()).hexdigest(),
                document["output"]["sha512"],
            )
            self.assertEqual(17, len(document["vector_layers"]))
            self.assertEqual("python", document["tools"]["huavd-map-build"])
            self.assertEqual("20261003.base", document["huavd_record"]["package_version"])

    def test_missing_manual_source_keeps_nullable_lineage_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            evidence = FileSystemManifestEvidenceReader().source(
                f"{directory}/missing.pbf", f"{directory}/missing.md5"
            )
        self.assertEqual(SourceEvidence(None, None, None), evidence)


class RasterManifestServiceTest(unittest.TestCase):
    def test_writes_candidate_manifest_with_cache_and_base_evidence(self) -> None:
        root = repository_root(Path(__file__))
        service = RasterManifestService(
            catalog_service(root), build_configuration_service(root),
            FileSystemPmtilesHeaderReader(), FileSystemManifestEvidenceReader(),
            FixedVersions(), FileDigestAdapter(), JsonManifestWriter(AtomicFileWriter()),
            lambda: "2026-10-03T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = "china-guangxi-20261003"
            outputs = workspace / "outputs"
            outputs.mkdir()
            base = outputs / f"{session}.base.pmtiles"
            write_header(base, 0, 15)
            (outputs / f"{session}.base.manifest.json").write_text(
                json.dumps({"vector_layers": ["road", "water"]}), encoding="utf-8"
            )
            candidate = workspace / f"cache/bake/{session}/candidate.pmtiles"
            candidate.parent.mkdir(parents=True)
            write_header(
                candidate, 3, 8, tile_type=4, tile_compression=1, tile_count=2
            )
            plan = {"tile_count": 2, "tiles_by_zoom": {"3": 2},
                    "bounds": [100, 20, 110, 30], "bbox_padding_tiles": 1}
            (candidate.parent / "plan.json").write_text(
                json.dumps(plan), encoding="utf-8"
            )
            (candidate.parent / "tiles.tsv").write_text("3\t1\t1\n3\t1\t2\n")
            (candidate.parent / "inputs.sha512").write_text("fingerprint\n")
            source = workspace / f"staging/{session}/source.osm.pbf"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"pbf")
            manifest = candidate.parent / "candidate.manifest.json"
            result = service.run(RasterManifestRequest(
                RegionId("china/guangxi"), BuildDate("20261003"),
                SessionId(session), directory, str(candidate), str(manifest), 2, 256,
            ))
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(str(manifest), result)
            self.assertEqual(2, document["raster_bake"]["plan"]["requested_tile_count"])
            self.assertEqual(["road", "water"], document["raster_bake"]["base_input"]["vector_layers"])
            self.assertFalse((outputs / f"{session}.raster_bake.manifest.json").exists())
            self.assertIsInstance(raster_manifest_service(root), RasterManifestService)
