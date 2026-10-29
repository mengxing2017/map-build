import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.delivery.domain.manifest import SourceEvidence
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.south.adapter.filesystem.metadata import (
    FileSystemPmtilesHeaderReader,
)
from huavd_map_build.delivery.south.adapter.filesystem.manifest import (
    FileSystemManifestEvidenceReader,
)
from huavd_map_build.quality.domain.vector import (
    VectorContractExpectations,
    verify_vector_contract,
)
from huavd_map_build.quality.north.local.vector import VectorQualityGate
from huavd_map_build.quality.south.adapter.filesystem.vector import (
    FileSystemVectorQualityReader,
)
from huavd_map_build.quality.south.adapter.process.pmtiles_metadata import (
    ProcessPmtilesMetadataReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role
from backend.tests.test_manifest import write_header


class FixedMetadataReader:
    def __init__(self, document: dict) -> None:
        self.document = document

    def embedded_metadata(self, path: str) -> dict:
        return self.document


class VectorQualityDomainTest(unittest.TestCase):
    @staticmethod
    def expectations() -> VectorContractExpectations:
        return VectorContractExpectations(
            "china/guangxi", "20261003", "base",
            "china-guangxi-20261003.base",
            "outputs/china-guangxi-20261003.base.pmtiles", 0, 15,
            "geofabrik",
            "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf",
            "geofabrik-guangxi-2026-10-03",
            "osm-china-guangxi", "cn-45-base", "20261003.base", "osm-dev",
            ("zh-Hans", "en", "ja", "ko"),
            ("zh-Hans", "en", "ja", "ko"),
            SourceEvidence(None, None, None),
        )

    def test_reports_independent_contract_failures(self) -> None:
        report = verify_vector_contract(
            header=PmtilesHeader(4, 1, 0, 1, (0, 0, 1, 1), 1, 16000, 1000),
            metadata={"bounds": [2, 2, 3, 3], "vector_layers": []},
            manifest={"output": {"size_bytes": 1, "sha512": "bad"},
                      "vector_layers": [], "huavd_record": {"package_version": ""}},
            attribution={},
            expected_metadata_layers=[{"id": "road"}], expected_layer_names=["road"],
            expected_tippecanoe={"min_zoom": 0},
            actual_size=2, actual_sha512="good", expected_profile=None,
            expected_profile_schema=None,
            expectations=self.expectations(),
        )
        codes = {finding.code for finding in report.findings}
        self.assertIn("header-tile-type", codes)
        self.assertIn("header-root-directory", codes)
        self.assertIn("manifest-sha512", codes)
        self.assertIn("metadata-bounds", codes)
        self.assertIn("metadata-layers", codes)
        self.assertIn("manifest-package-version", codes)
        self.assertIn("manifest-identity", codes)
        self.assertIn("manifest-build-time", codes)
        self.assertIn("manifest-source", codes)
        self.assertIn("manifest-tippecanoe", codes)
        self.assertIn("manifest-record-catalog", codes)
        self.assertIn("manifest-record-locales", codes)
        self.assertIn("manifest-record-release", codes)
        self.assertIn("metadata-identity", codes)
        self.assertIn("metadata-source-id", codes)
        self.assertIn("metadata-build-time", codes)
        self.assertIn("metadata-center", codes)
        self.assertIn("metadata-available-locales", codes)
        self.assertIn("metadata-style-locales", codes)
        self.assertIn("attribution-contract", codes)

    def test_reports_artifact_identity_and_range_tampering(self) -> None:
        header = PmtilesHeader(1, 2, 0, 15, (0, 0, 1, 1), 2, 0, 0)
        metadata = {
            "name": "wrong", "format": "pbf", "huavd:region": "wrong",
            "huavd:asset-role": "base-vector",
            "huavd:source-id": "osm-china-guangxi",
            "huavd:build-time": "2026-02-30T00:00:00Z",
            "minzoom": 1, "maxzoom": 15,
            "bounds": [0, 0, 1, 1], "vector_layers": [],
            "attribution": "OpenStreetMap contributors",
            "huavd:data-license": "ODbL-1.0",
            "huavd:available-locales": ["zh-Hans"],
            "huavd:style-locales": ["zh-Hans"],
        }
        manifest = {
            "schema": "huavd-map-build/v1", "region": "wrong",
            "yyyymmdd": "20261003", "build_id": "2026-02-30T00:00:00Z",
            "output": {
                "path": "outputs/wrong.pmtiles", "size_bytes": 1,
                "sha512": "digest", "tile_range": {
                    "min_zoom": 1, "max_zoom": 15, "bounds": [0, 0, 1, 1],
                },
            }, "vector_layers": [], "huavd_record": {
                "name": "wrong", "asset_role": "base-vector",
                "format": "pmtiles", "transport": "offline",
                "coord_system": "EPSG:3857", "package_version": "20261003.base",
                "id": "cn-45-base", "source_id": "osm-china-guangxi",
                "style_id": "osm-dev", "source_type": "osm-pbf",
                "available_locales": ["zh-Hans", "en", "ja", "ko"],
                "style_locales": ["zh-Hans", "en", "ja", "ko"],
                "source_revision": "geofabrik-guangxi-2026-10-03",
                "released_at": "2026-02-30T00:00:00Z",
                "bundle_id": "china-guangxi-20261003-standard",
                "activation": "manual",
            }, "license": {
                "data_license": "ODbL-1.0",
                "attribution": "OpenStreetMap contributors",
            },
        }
        report = verify_vector_contract(
            header=header, metadata=metadata, manifest=manifest,
            attribution={
                "data_license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "sources": [{
                    "vendor": "geofabrik",
                    "url": self.expectations().source_url,
                }],
            },
            expected_metadata_layers=[], expected_layer_names=[], actual_size=1,
            expected_tippecanoe={},
            actual_sha512="digest", expected_profile=None,
            expected_profile_schema=None, expectations=self.expectations(),
        )
        codes = {finding.code for finding in report.findings}
        self.assertTrue({
            "manifest-identity", "manifest-output-path", "manifest-tile-range",
            "manifest-record-identity", "metadata-identity",
            "metadata-zoom-range", "metadata-available-locales",
            "metadata-style-locales", "manifest-build-time",
            "manifest-record-release", "metadata-build-time",
        }.issubset(codes))


class VectorQualityGateTest(unittest.TestCase):
    def test_valid_base_artifact_passes(self) -> None:
        root = repository_root(Path(__file__))
        configuration = build_configuration_service(root)
        region, date = RegionId("china/guangxi"), BuildDate("20261003")
        with tempfile.TemporaryDirectory() as directory:
            outputs = Path(directory) / "outputs"
            outputs.mkdir()
            stem = "china-guangxi-20261003.base"
            source = Path(directory) / "staging/china-guangxi-20261003/source.osm.pbf"
            source.parent.mkdir(parents=True)
            mirror = Path(directory) / "mirror/guangxi-latest.osm.pbf"
            mirror.parent.mkdir()
            mirror.write_bytes(b"manual-pbf-fixture")
            source.symlink_to(mirror)
            md5 = Path(f"{mirror}.md5")
            md5.write_text(
                f"{hashlib.md5(mirror.read_bytes()).hexdigest()}  guangxi-latest.osm.pbf\n",
                encoding="ascii",
            )
            evidence_reader = FileSystemManifestEvidenceReader()
            evidence = evidence_reader.source(str(source), str(md5))
            self.assertEqual(
                hashlib.sha256(b"manual-pbf-fixture").hexdigest(), evidence.sha256
            )
            pmtiles = outputs / f"{stem}.pmtiles"
            write_header(pmtiles, max_zoom=14)
            digest = hashlib.sha512(pmtiles.read_bytes()).hexdigest()
            tippecanoe = configuration.tippecanoe(region.value, "base")
            names = list(tippecanoe["source_layers"])
            layers = configuration.vector_layers(region.value, "base", 14)
            manifest = {
                "schema": "huavd-map-build/v1", "region": region.value,
                "yyyymmdd": date.value, "build_id": "2026-10-03T00:00:00Z",
                "source": {
                    "vendor": "geofabrik",
                    "url": "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf",
                    "downloaded_at": evidence.downloaded_at,
                    "size_bytes": evidence.size_bytes, "md5": evidence.md5,
                    "sha256": evidence.sha256,
                    "osm_timestamp": None,
                }, "output": {
                    "path": f"outputs/{stem}.pmtiles",
                    "size_bytes": pmtiles.stat().st_size, "sha512": digest,
                    "tile_range": {
                        "min_zoom": 0, "max_zoom": 14,
                        "bounds": [10.0, 20.0, 12.0, 24.0],
                    },
                },
                "vector_layers": names,
                "tippecanoe": tippecanoe,
                "huavd_record": {
                    "name": stem, "asset_role": "base-vector",
                    "format": "pmtiles", "transport": "offline",
                    "coord_system": "EPSG:3857",
                    "package_version": "20261003.base",
                    "id": "cn-45-base", "source_id": "osm-china-guangxi",
                    "style_id": "osm-dev", "source_type": "osm-pbf",
                    "available_locales": ["zh-Hans", "en", "ja", "ko"],
                    "style_locales": ["zh-Hans", "en", "ja", "ko"],
                    "source_revision": "geofabrik-guangxi-2026-10-03",
                    "released_at": "2026-10-03T00:00:00Z",
                    "bundle_id": "china-guangxi-20261003-standard",
                    "activation": "manual",
                },
                "license": {
                    "data_license": "ODbL-1.0",
                    "attribution": "© OpenStreetMap contributors",
                },
            }
            (outputs / f"{stem}.manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )
            (outputs / f"{stem}.attribution.json").write_text(json.dumps({
                "data_license": "ODbL-1.0",
                "attribution": "© OpenStreetMap contributors",
                "sources": [{
                    "vendor": "geofabrik",
                    "url": "https://download.geofabrik.de/asia/china/guangxi-latest.osm.pbf",
                }],
            }), encoding="utf-8")
            metadata = {
                "name": stem, "format": "pbf",
                "huavd:region": region.value,
                "huavd:asset-role": "base-vector",
                "huavd:source-id": "osm-china-guangxi",
                "huavd:build-time": "2026-10-03T00:00:00Z",
                "minzoom": 0, "maxzoom": 14,
                "center": [11.0, 22.0, 6],
                "bounds": [10.0, 20.0, 12.0, 24.0], "vector_layers": layers,
                "attribution": "© OpenStreetMap contributors",
                "huavd:data-license": "ODbL-1.0",
                "huavd:available-locales": ["zh-Hans", "en", "ja", "ko"],
                "huavd:style-locales": ["zh-Hans", "en", "ja", "ko"],
            }
            gate = VectorQualityGate(
                catalog_service(root), configuration, FileSystemPmtilesHeaderReader(),
                FileSystemVectorQualityReader(), FixedMetadataReader(metadata),
                FileDigestAdapter(), evidence_reader,
            )
            report = gate.verify(
                region=region, build_date=date, role=Role.BASE, workdir=directory
            )
            for invalid in ("not-a-checksum", "0" * 32):
                md5.write_text(invalid)
                failed = gate.verify(
                    region=region, build_date=date, role=Role.BASE, workdir=directory
                )
                self.assertFalse(failed.passed)
                self.assertIn("source-evidence", {item.code for item in failed.findings})
            md5.write_text(
                f"{hashlib.md5(b'manual-pbf-fixture').hexdigest()}  guangxi-latest.osm.pbf\n",
                encoding="ascii",
            )
            manifest_path = outputs / f"{stem}.manifest.json"
            original = json.loads(manifest_path.read_text(encoding="utf-8"))
            for invalid in (None, "0" * 63, "A" * 64):
                tampered = json.loads(json.dumps(original))
                tampered["source"]["sha256"] = invalid
                manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
                failed = gate.verify(
                    region=region, build_date=date, role=Role.BASE, workdir=directory
                )
                self.assertFalse(failed.passed)
                self.assertIn(
                    "manifest-source-sha256", {item.code for item in failed.findings}
                )
            manifest_path.write_text(json.dumps(original), encoding="utf-8")
        self.assertTrue(report.passed, report.as_dict())


class ProcessPmtilesMetadataReaderTest(unittest.TestCase):
    def test_reads_json_with_argument_vector(self) -> None:
        result = Mock(returncode=0, stdout='{"name":"map"}', stderr="")
        with patch("shutil.which", return_value="/tools/pmtiles"), patch(
            "subprocess.run", return_value=result
        ) as run:
            document = ProcessPmtilesMetadataReader().embedded_metadata("map.pmtiles")
        self.assertEqual("map", document["name"])
        self.assertEqual(
            ["/tools/pmtiles", "show", "map.pmtiles", "--metadata"],
            run.call_args.args[0],
        )

    def test_rejects_invalid_json(self) -> None:
        with patch("shutil.which", return_value="/tools/pmtiles"), patch(
            "subprocess.run", return_value=Mock(returncode=0, stdout="not-json")
        ):
            with self.assertRaisesRegex(ValueError, "invalid metadata JSON"):
                ProcessPmtilesMetadataReader().embedded_metadata("map.pmtiles")
