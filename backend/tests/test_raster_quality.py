import unittest
import json
from pathlib import Path
from unittest.mock import Mock

from huavd_map_build.bootstrap import catalog_service, repository_root
from huavd_map_build.delivery.domain.attribution import AttributionDocument
from huavd_map_build.delivery.domain.integrity import ArtifactIntegrityReport
from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
from huavd_map_build.delivery.south.adapter.filesystem.manifest import FileSystemManifestEvidenceReader
from huavd_map_build.delivery.south.adapter.filesystem.metadata import FileSystemPmtilesHeaderReader
from huavd_map_build.delivery.south.adapter.filesystem.raster_publication import FileSystemRasterCandidatePublisher
from huavd_map_build.production.north.local.raster_finalize import RasterFinalizationRequest, RasterFinalizationService
from huavd_map_build.quality.north.local.raster import RasterQualityGate
from backend.tests.test_manifest import raster_workspace
from huavd_map_build.quality.domain.raster import (
    RasterContractExpectations,
    verify_raster_contract,
)


class RasterQualityDomainTest(unittest.TestCase):
    def expectations(self) -> RasterContractExpectations:
        return RasterContractExpectations(
            region="china/guangxi", stem="china-guangxi-20261003.raster_bake",
            output_path="outputs/china-guangxi-20261003.raster_bake.pmtiles",
            source_id="osm-geofabrik-china-guangxi", tile_count=2, tile_size=256,
            actual_size=127, actual_sha512="a" * 128,
            base_file="china-guangxi-20261003.base.pmtiles",
            base_sha512="b" * 128, plan_sha512="c" * 128,
            tiles_sha512="d" * 128, input_fingerprint="fingerprint",
            base_source={"vendor": "local", "url": None},
            source_revision="local-custom-2026-10-03",
        )

    def test_accepts_consistent_static_contract(self) -> None:
        expected = self.expectations()
        header = PmtilesHeader(
            4, 1, 3, 8, (100, 20, 110, 30), addressed_tiles_count=2
        )
        metadata = {
            "name": expected.stem, "format": "webp",
            "huavd:region": expected.region,
            "huavd:source-id": expected.source_id,
            "huavd:asset-role": "raster-baked", "vector_layers": [],
            "huavd:raster-encoding": "webp", "huavd:tile-count": 2,
            "huavd:raster-tile-size": 256, "minzoom": 3, "maxzoom": 8,
            "bounds": [100, 20, 110, 30],
        }
        manifest = {
            "source": expected.base_source,
            "huavd_record": {"source_revision": expected.source_revision},
            "output": {"path": expected.output_path, "size_bytes": 127,
                       "sha512": "a" * 128},
            "vector_layers": [],
            "raster_bake": {
                "encoding": "webp", "tile_count": 2, "tile_size": 256,
                "tile_type": 4, "tile_compression": 1,
                "base_input": {"file": expected.base_file,
                               "sha512": "b" * 128},
                "plan": {"plan_sha512": "c" * 128,
                         "tiles_sha512": "d" * 128,
                         "input_fingerprint": "fingerprint",
                         "requested_tile_count": 2},
            },
        }
        report = verify_raster_contract(
            header=header, metadata=metadata, manifest=manifest,
            attribution=AttributionDocument.osm("local", None).as_dict(),
            expectations=expected,
        )
        self.assertTrue(report.passed, report.as_dict())

    def test_reports_independent_header_and_plan_failures(self) -> None:
        report = verify_raster_contract(
            header=PmtilesHeader(1, 2, 3, 8, (0, 0, 1, 1)),
            metadata={}, manifest={}, attribution={}, expectations=self.expectations(),
        )
        codes = {finding.code for finding in report.findings}
        self.assertIn("header-tile-type", codes)
        self.assertIn("manifest-plan", codes)
        self.assertIn("metadata-raster", codes)


class RasterQualityGateTest(unittest.TestCase):
    def gate(self, request):
        catalog = catalog_service(repository_root(Path(__file__)))
        header = FileSystemPmtilesHeaderReader().read(request.pmtiles_path)
        metadata = {
            "name": f"{request.session.value}.raster_bake", "format": "webp",
            "huavd:region": request.region.value,
            "huavd:source-id": catalog.region_settings(request.region, "raster_bake", "20261003")["source_id"],
            "huavd:asset-role": "raster-baked", "vector_layers": [],
            "huavd:raster-encoding": "webp", "huavd:tile-count": 2,
            "huavd:raster-tile-size": 256, "minzoom": header.min_zoom,
            "maxzoom": header.max_zoom, "bounds": list(header.bounds),
        }
        return RasterQualityGate(
            catalog, FileSystemPmtilesHeaderReader(),
            Mock(embedded_metadata=Mock(return_value=metadata)),
            FileDigestAdapter(), FileSystemManifestEvidenceReader(),
        )

    def verify(self, request):
        return self.gate(request).verify(request)

    @staticmethod
    def write_attribution(request, source):
        path = Path(request.manifest_path.removesuffix(".manifest.json") + ".attribution.json")
        path.write_text(json.dumps(AttributionDocument.osm(source["vendor"], source["url"]).as_dict()))
        return path

    def test_accepts_base_lineage_without_reading_changed_pbf(self) -> None:
        for region, vendor in (("china/guangxi", "local"), ("china/guangxi", "geofabrik"),
                               ("china/xizang", "geofabrik")):
            with self.subTest(region=region, vendor=vendor), raster_workspace(region, vendor) as fixture:
                service, request, _base, document = fixture
                service.run(request)
                self.write_attribution(request, document["source"])
                report = self.verify(request)
                self.assertTrue(report.passed, report.as_dict())

    def test_rejects_raster_source_attribution_and_revision_tampering(self) -> None:
        changes = (("source", {"vendor": "local", "url": None}, "source-base-consistency"),
                   ("source", {"vendor": "geofabrik", "url": None}, "attribution-contract"),
                   ("huavd_record", {"source_revision": "wrong"}, "manifest-source-revision"),
                   ("attribution", {}, "attribution-contract"))
        for key, value, code in changes:
            with self.subTest(key=key, value=value), raster_workspace(vendor="geofabrik") as fixture:
                service, request, _base, base_document = fixture
                service.run(request)
                attribution = self.write_attribution(request, base_document["source"])
                path = attribution if key == "attribution" else Path(request.manifest_path)
                document = json.loads(path.read_text())
                if key == "attribution":
                    document = value
                else:
                    document[key] = value
                path.write_text(json.dumps(document))
                report = self.verify(request)
                self.assertFalse(report.passed)
                self.assertIn(code, {finding.code for finding in report.findings})

    def test_rejects_base_tampering_after_candidate_was_written(self) -> None:
        for key, value in (("region", "wrong"), ("output.sha512", "0" * 128),
                           ("output.size_bytes", 1), ("source.vendor", "unknown")):
            with self.subTest(key=key), raster_workspace() as fixture:
                service, request, base, document = fixture
                service.run(request)
                self.write_attribution(request, document["source"])
                parent, _, field = key.rpartition(".")
                (document[parent] if parent else document)[field] = value
                base.with_suffix(".manifest.json").write_text(json.dumps(document))
                report = self.verify(request)
                self.assertFalse(report.passed)
                self.assertIn("source-base-consistency", {finding.code for finding in report.findings})

    def test_real_gate_prevents_promotion_when_staged_attribution_is_wrong(self) -> None:
        with raster_workspace(vendor="geofabrik") as fixture:
            manifest_service, request, _base, _document = fixture
            catalog = catalog_service(repository_root(Path(__file__)))
            candidates = Mock(wraps=FileSystemRasterCandidatePublisher())
            publication = Mock()

            def write_wrong_attribution(paths, document):
                Path(paths.attribution).write_text(json.dumps(
                    AttributionDocument.osm("local", None).as_dict()
                ))

            finalizer = RasterFinalizationService(
                catalog, Mock(run=Mock(return_value="metadata.json")), manifest_service,
                Mock(write=Mock(side_effect=write_wrong_attribution)), self.gate(request),
                Mock(verify=Mock(return_value=ArtifactIntegrityReport((), ()))),
                candidates, publication,
            )
            result = finalizer.run(RasterFinalizationRequest(
                request.region, request.build_date, request.session, request.workdir,
                request.pmtiles_path, request.tile_count, request.tile_size,
            ))
            self.assertFalse(result.published)
            self.assertIn("attribution-contract", {item.code for item in result.semantic.findings})
            candidates.promote.assert_not_called()
            candidates.discard.assert_called_once()
            publication.publish_integrity_metadata.assert_not_called()
            self.assertFalse(Path(result.paths.ready).exists())
            self.assertFalse(Path(result.paths.pmtiles).exists())


if __name__ == "__main__":
    unittest.main()
