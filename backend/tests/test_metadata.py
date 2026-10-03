import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.delivery.domain.metadata import (
    MetadataEditError,
    MetadataRequest,
    RasterMetadataRequest,
    MetadataVerificationError,
    MissingPmtilesToolError,
    PmtilesHeader,
    compile_vector_metadata,
    compile_raster_metadata,
)
from huavd_map_build.delivery.north.local.metadata import (
    RasterMetadataService,
    VectorMetadataService,
)
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.south.adapter.filesystem.metadata import (
    FileSystemMetadataStore,
    FileSystemPmtilesHeaderReader,
)
from huavd_map_build.delivery.south.adapter.process.pmtiles_metadata import (
    ProcessPmtilesMetadataEditor,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


def write_header(path: Path, tile_type: int = 1, tile_compression: int = 2) -> None:
    payload = bytearray(127)
    payload[:8] = b"PMTiles\x03"
    payload[97:102] = bytes((2, tile_compression, tile_type, 0, 15))
    struct.pack_into("<iiii", payload, 102, 100_000_000, 200_000_000,
                     120_000_000, 240_000_000)
    path.write_bytes(payload)


class RecordingEditor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def edit(self, pmtiles_path: str, metadata_path: str) -> None:
        self.calls.append((pmtiles_path, metadata_path))


class MetadataDomainTest(unittest.TestCase):
    def test_compiles_vector_contract_and_rejects_non_mvt(self) -> None:
        header = PmtilesHeader(1, 2, 0, 15, (10.0, 20.0, 12.0, 24.0))
        document = compile_vector_metadata(
            stem="china-guangxi-20261003.base", region=RegionId("china/guangxi"),
            role=Role.BASE, header=header, vector_layers=[{"id": "road"}],
            source_id="osm-geofabrik-china-guangxi", available_locales=("zh-Hans",),
            style_locales=("zh-Hans",), build_time="2026-10-03T00:00:00Z",
        )
        self.assertEqual([11.0, 22.0, 6], document["center"])
        self.assertEqual("base-vector", document["huavd:asset-role"])
        with self.assertRaisesRegex(MetadataVerificationError, "tile_type"):
            compile_vector_metadata(
                stem="x", region=RegionId("china"), role=Role.BASE,
                header=PmtilesHeader(4, 1, 0, 1, (0, 0, 1, 1)),
                vector_layers=[], source_id="source", available_locales=(),
                style_locales=(), build_time="now",
            )

    def test_compiles_raster_contract_and_rejects_invalid_header(self) -> None:
        document = compile_raster_metadata(
            stem="china-guangxi-20261003.raster_bake",
            region=RegionId("china/guangxi"),
            header=PmtilesHeader(4, 1, 0, 14, (10.0, 20.0, 12.0, 24.0)),
            source_id="osm-geofabrik-china-guangxi",
            available_locales=("zh-Hans",), style_locales=("zh-Hans",),
            build_time="2026-10-03T00:00:00Z", tile_count=100, tile_size=256,
        )
        self.assertEqual("webp", document["format"])
        self.assertEqual([], document["vector_layers"])
        self.assertEqual("raster-baked", document["huavd:asset-role"])
        self.assertEqual(100, document["huavd:tile-count"])
        self.assertEqual(256, document["huavd:raster-tile-size"])
        with self.assertRaisesRegex(MetadataVerificationError, "tile_compression"):
            compile_raster_metadata(
                stem="x", region=RegionId("china"),
                header=PmtilesHeader(4, 2, 0, 1, (0, 0, 1, 1)),
                source_id="source", available_locales=(), style_locales=(),
                build_time="now", tile_count=1, tile_size=256,
            )


class MetadataAdapterTest(unittest.TestCase):
    def test_reads_pmtiles_v3_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "map.pmtiles"
            write_header(path)
            header = FileSystemPmtilesHeaderReader().read(str(path))
        self.assertEqual(1, header.tile_type)
        self.assertEqual(2, header.tile_compression)
        self.assertEqual((10.0, 20.0, 12.0, 24.0), header.bounds)

    def test_editor_uses_argument_vector_and_maps_errors(self) -> None:
        with patch("shutil.which", return_value="/tools/pmtiles"), patch(
            "subprocess.run", return_value=Mock(returncode=0)
        ) as run:
            ProcessPmtilesMetadataEditor().edit("map.pmtiles", "metadata.json")
        self.assertEqual(
            ["/tools/pmtiles", "edit", "map.pmtiles", "--metadata=metadata.json"],
            run.call_args.args[0],
        )
        with patch("shutil.which", return_value=None):
            with self.assertRaises(MissingPmtilesToolError):
                ProcessPmtilesMetadataEditor().edit("map", "metadata")
        with patch("shutil.which", return_value="/tool"), patch(
            "subprocess.run", return_value=Mock(returncode=7)
        ):
            with self.assertRaisesRegex(MetadataEditError, "exit code 7"):
                ProcessPmtilesMetadataEditor().edit("map", "metadata")


class VectorMetadataServiceTest(unittest.TestCase):
    def test_writes_metadata_invokes_editor_and_refreshes_sidecar(self) -> None:
        root = repository_root(Path(__file__))
        editor = RecordingEditor()
        service = VectorMetadataService(
            catalog_service(root), build_configuration_service(root),
            FileSystemPmtilesHeaderReader(), editor,
            FileSystemMetadataStore(AtomicFileWriter(), FileDigestAdapter()),
            lambda: "2026-10-03T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            pmtiles = Path(directory) / "manual.pmtiles"
            write_header(pmtiles)
            metadata = service.run(MetadataRequest(
                RegionId("china/guangxi"), BuildDate("20261003"),
                SessionId("china-guangxi-20261003"), Role.BASE, directory,
                str(pmtiles),
            ))
            document = json.loads(Path(metadata).read_text(encoding="utf-8"))
            self.assertEqual(17, len(document["vector_layers"]))
            self.assertEqual("china/guangxi", document["huavd:region"])
            self.assertEqual([(str(pmtiles), metadata)], editor.calls)
            expected = hashlib.sha512(pmtiles.read_bytes()).hexdigest()
            self.assertEqual(
                f"{expected}  manual.pmtiles\n",
                Path(f"{pmtiles}.sha512").read_text(encoding="utf-8"),
            )


class RasterMetadataServiceTest(unittest.TestCase):
    def test_writes_raster_metadata_edits_candidate_and_refreshes_sidecar(self) -> None:
        root = repository_root(Path(__file__))
        editor = RecordingEditor()
        service = RasterMetadataService(
            catalog_service(root), build_configuration_service(root),
            FileSystemPmtilesHeaderReader(), editor,
            FileSystemMetadataStore(AtomicFileWriter(), FileDigestAdapter()),
            lambda: "2026-10-03T00:00:00Z",
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.pmtiles"
            write_header(candidate, tile_type=4, tile_compression=1)
            metadata = service.run(RasterMetadataRequest(
                RegionId("china/guangxi"), BuildDate("20261003"),
                SessionId("china-guangxi-20261003"), directory,
                str(candidate), 25, 256,
            ))
            document = json.loads(Path(metadata).read_text(encoding="utf-8"))
            sidecar = Path(f"{candidate}.sha512").read_text(encoding="utf-8")
        self.assertEqual("raster-baked", document["huavd:asset-role"])
        self.assertEqual(25, document["huavd:tile-count"])
        self.assertEqual([(str(candidate), metadata)], editor.calls)
        self.assertTrue(sidecar.endswith("  candidate.pmtiles\n"))

    def test_invalid_candidate_header_prevents_editor_call(self) -> None:
        root = repository_root(Path(__file__))
        editor = RecordingEditor()
        service = RasterMetadataService(
            catalog_service(root), build_configuration_service(root),
            FileSystemPmtilesHeaderReader(), editor,
            FileSystemMetadataStore(AtomicFileWriter(), FileDigestAdapter()),
        )
        with tempfile.TemporaryDirectory() as directory:
            candidate = Path(directory) / "candidate.pmtiles"
            write_header(candidate, tile_type=1, tile_compression=2)
            with self.assertRaisesRegex(MetadataVerificationError, "tile_type"):
                service.run(RasterMetadataRequest(
                    RegionId("china/guangxi"), BuildDate("20261003"),
                    SessionId("china-guangxi-20261003"), directory,
                    str(candidate), 1, 256,
                ))
        self.assertEqual([], editor.calls)
