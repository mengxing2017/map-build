import unittest

from huavd_map_build.delivery.domain.metadata import PmtilesHeader
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
            expectations=expected,
        )
        self.assertTrue(report.passed, report.as_dict())

    def test_reports_independent_header_and_plan_failures(self) -> None:
        report = verify_raster_contract(
            header=PmtilesHeader(1, 2, 3, 8, (0, 0, 1, 1)),
            metadata={}, manifest={}, expectations=self.expectations(),
        )
        codes = {finding.code for finding in report.findings}
        self.assertIn("header-tile-type", codes)
        self.assertIn("manifest-plan", codes)
        self.assertIn("metadata-raster", codes)


if __name__ == "__main__":
    unittest.main()
