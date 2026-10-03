import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.delivery.domain.attribution import (
    AttributionContractError,
    AttributionDocument,
)
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.north.local.verification import ArtifactFileVerifier
from huavd_map_build.delivery.north.local.publication import ArtifactPublicationService
from huavd_map_build.delivery.north.local.attribution import AttributionWriterService
from huavd_map_build.delivery.north.local.sidecar import Sha512SidecarWriterService
from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
from huavd_map_build.delivery.south.adapter.filesystem.artifact_store import (
    FileSystemArtifactStore,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class ArtifactPathsTest(unittest.TestCase):
    def _paths(self, role: Role) -> ArtifactPaths:
        return ArtifactPaths(
            ArtifactIdentity(
                RegionId("china/guangxi"), BuildDate("20260818"), role
            ),
            "/tmp/maps/outputs",
        )

    def test_core_paths_match_existing_output_contract(self) -> None:
        paths = self._paths(Role.BASE)
        self.assertEqual(
            "/tmp/maps/outputs/china-guangxi-20260818.base.pmtiles", paths.pmtiles
        )
        self.assertEqual(f"{paths.pmtiles}.sha512", paths.sha512)
        self.assertEqual(
            "/tmp/maps/outputs/china-guangxi-20260818.base.manifest.json",
            paths.manifest,
        )

    def test_raster_closure_contains_base_and_render_support(self) -> None:
        closure = self._paths(Role.RASTER_BAKE).consumer_closure()
        self.assertIn(
            "/tmp/maps/outputs/china-guangxi-20260818.base.pmtiles", closure
        )
        self.assertIn(
            "/tmp/maps/outputs/china-guangxi-20260818.style-raster.json", closure
        )
        self.assertIn("/tmp/maps/outputs/china-guangxi-20260818.glyphs", closure)


class AttributionDocumentTest(unittest.TestCase):
    def test_geofabrik_osm_contract(self) -> None:
        document = AttributionDocument.geofabrik_osm(
            "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf"
        )
        self.assertEqual(
            {
                "data_license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "sources": [
                    {
                        "vendor": "geofabrik",
                        "url": "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf",
                    }
                ],
            },
            document.as_dict(),
        )

    def test_invalid_source_url_is_rejected(self) -> None:
        with self.assertRaises(AttributionContractError):
            AttributionDocument.geofabrik_osm("mirror/guangxi.osm.pbf")

    def test_writer_uses_artifact_path_and_leaves_no_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = ArtifactPaths(
                ArtifactIdentity(
                    RegionId("china/guangxi"), BuildDate("20260818"), Role.BASE
                ),
                directory,
            )
            document = AttributionDocument.geofabrik_osm(
                "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf"
            )
            output = AttributionWriterService(AtomicFileWriter()).write(paths, document)
            written = json.loads(Path(output).read_text(encoding="utf-8"))
            temporary_files = list(Path(directory).glob(".*.tmp"))
        self.assertEqual(document.as_dict(), written)
        self.assertEqual([], temporary_files)


class FileDigestAdapterTest(unittest.TestCase):
    def test_supported_checksum_algorithms_match_standard_library(self) -> None:
        content = b"geofabrik-pbf-fixture"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.osm.pbf"
            path.write_bytes(content)
            adapter = FileDigestAdapter(chunk_size=3)
            actual = {
                algorithm: adapter.checksum(str(path), algorithm)
                for algorithm in ("md5", "sha256", "sha512")
            }
        self.assertEqual(hashlib.md5(content).hexdigest(), actual["md5"])
        self.assertEqual(hashlib.sha256(content).hexdigest(), actual["sha256"])
        self.assertEqual(hashlib.sha512(content).hexdigest(), actual["sha512"])

    def test_unsupported_checksum_algorithm_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported digest algorithm"):
            FileDigestAdapter().checksum("unused", "sha1")

    def test_sha512_is_streamed_with_standard_digest(self) -> None:
        content = b"huavd-map-build\n" * 1024
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "artifact.bin"
            path.write_bytes(content)
            actual = FileDigestAdapter(chunk_size=17).sha512(str(path))
        self.assertEqual(hashlib.sha512(content).hexdigest(), actual)

    def test_sha512_chunks_preserves_binary_boundaries(self) -> None:
        chunks = [b"huavd\x00", "地图".encode(), b"\nmap-build"]
        actual = FileDigestAdapter().sha512_chunks(iter(chunks))
        self.assertEqual(hashlib.sha512(b"".join(chunks)).hexdigest(), actual)

    def test_atomic_sidecar_writer_uses_sha512sum_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "map.pmtiles"
            artifact.write_bytes(b"map-v1")
            service = Sha512SidecarWriterService(
                FileSystemArtifactStore(), FileDigestAdapter(), AtomicFileWriter()
            )
            output = service.write(str(artifact))
            sidecar = Path(output).read_text(encoding="ascii")
            temporary_files = list(Path(directory).glob(".*.tmp"))
        expected = hashlib.sha512(b"map-v1").hexdigest()
        self.assertEqual(f"{expected}  map.pmtiles\n", sidecar)
        self.assertEqual([], temporary_files)

    def test_sidecar_writer_rejects_missing_input(self) -> None:
        service = Sha512SidecarWriterService(
            FileSystemArtifactStore(), FileDigestAdapter(), AtomicFileWriter()
        )
        with self.assertRaisesRegex(ValueError, "required file does not exist"):
            service.write("/tmp/huavd-definitely-missing.pmtiles")


class ArtifactFileVerifierTest(unittest.TestCase):
    def _paths(self, directory: str, role: Role = Role.BASE) -> ArtifactPaths:
        return ArtifactPaths(
            ArtifactIdentity(
                RegionId("china/guangxi"), BuildDate("20260818"), role
            ),
            directory,
        )

    def _write_core(self, paths: ArtifactPaths) -> None:
        Path(paths.pmtiles).write_bytes(b"pmtiles-fixture")
        Path(paths.manifest).write_text("{}\n", encoding="utf-8")
        Path(paths.attribution).write_text("{}\n", encoding="utf-8")
        digest = hashlib.sha512(b"pmtiles-fixture").hexdigest()
        Path(paths.sha512).write_text(
            f"{digest}  {Path(paths.pmtiles).name}\n", encoding="ascii"
        )

    def _write_ready(self, paths: ArtifactPaths) -> None:
        document = {
            "schema_version": 1,
            "role": paths.identity.role.value,
            "file": Path(paths.pmtiles).name,
            "sha512": FileDigestAdapter().sha512(paths.pmtiles),
            "manifest_sha512": FileDigestAdapter().sha512(paths.manifest),
            "attribution_sha512": FileDigestAdapter().sha512(paths.attribution),
            "published_at": "2026-10-03T12:00:00Z",
        }
        Path(paths.ready).write_text(json.dumps(document), encoding="utf-8")

    def test_valid_core_files_and_sidecar_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            self._write_core(paths)
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths)
        self.assertTrue(report.passed, report.failures)

    def test_digest_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory)
            self._write_core(paths)
            Path(paths.pmtiles).write_bytes(b"changed")
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths)
        self.assertEqual(["digest-mismatch"], [item.code for item in report.failures])

    def test_raster_consumer_closure_reports_missing_support(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory, Role.RASTER_BAKE)
            self._write_core(paths)
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths, require_consumer_closure=True)
        missing = [item.path for item in report.failures if item.code == "missing"]
        self.assertIn(paths.raster_style, missing)
        self.assertIn(paths.glyphs, missing)

    def test_valid_ready_marker_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory, Role.RASTER_BAKE)
            self._write_core(paths)
            self._write_ready(paths)
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths, require_ready_marker=True)
        self.assertTrue(report.passed, report.failures)

    def test_stale_manifest_is_rejected_by_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = self._paths(directory, Role.RASTER_BAKE)
            self._write_core(paths)
            self._write_ready(paths)
            Path(paths.manifest).write_text('{"changed":true}\n', encoding="utf-8")
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths, require_ready_marker=True)
        self.assertIn("ready-manifest-sha512", [item.code for item in report.failures])


class ArtifactPublicationServiceTest(unittest.TestCase):
    def test_integrity_metadata_is_compatible_and_ready_is_written_last(self) -> None:
        writes: list[str] = []

        class RecordingWriter:
            def __init__(self) -> None:
                self._delegate = AtomicFileWriter()

            def write_text(self, path: str, content: str) -> None:
                self._delegate.write_text(path, content)
                writes.append(path)

        with tempfile.TemporaryDirectory() as directory:
            paths = ArtifactPaths(
                ArtifactIdentity(
                    RegionId("china/guangxi"),
                    BuildDate("20260818"),
                    Role.RASTER_BAKE,
                ),
                directory,
            )
            Path(paths.pmtiles).write_bytes(b"published-pmtiles")
            Path(paths.manifest).write_text("{}\n", encoding="utf-8")
            Path(paths.attribution).write_text("{}\n", encoding="utf-8")
            service = ArtifactPublicationService(
                FileSystemArtifactStore(), FileDigestAdapter(), RecordingWriter()
            )
            marker = service.publish_integrity_metadata(
                paths, published_at="2026-10-03T12:00:00Z"
            )
            report = ArtifactFileVerifier(
                FileSystemArtifactStore(), FileDigestAdapter()
            ).verify(paths, require_ready_marker=True)
            sidecar = Path(paths.sha512).read_text(encoding="ascii")
            temporary_files = list(Path(directory).glob(".*.tmp"))

        self.assertEqual([paths.sha512, paths.ready], writes)
        self.assertEqual(paths.ready, writes[-1])
        self.assertEqual(Path(paths.pmtiles).name, marker.file)
        self.assertTrue(sidecar.endswith(f"  {Path(paths.pmtiles).name}\n"))
        self.assertTrue(report.passed, report.failures)
        self.assertEqual([], temporary_files)

    def test_missing_manifest_does_not_publish_sidecar_or_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            paths = ArtifactPaths(
                ArtifactIdentity(
                    RegionId("china/guangxi"), BuildDate("20260818"), Role.BASE
                ),
                directory,
            )
            Path(paths.pmtiles).write_bytes(b"candidate")
            Path(paths.attribution).write_text("{}\n", encoding="utf-8")
            service = ArtifactPublicationService(
                FileSystemArtifactStore(), FileDigestAdapter(), AtomicFileWriter()
            )
            with self.assertRaisesRegex(ValueError, "missing artifact file"):
                service.publish_integrity_metadata(
                    paths, published_at="2026-10-03T12:00:00Z"
                )
            self.assertFalse(Path(paths.sha512).exists())
            self.assertFalse(Path(paths.ready).exists())
