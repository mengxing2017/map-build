import subprocess
import gzip
import unittest
from unittest.mock import patch

from huavd_map_build.quality.domain.tile import (
    TileCoordinate,
    TileSamplePlan,
    lonlat_to_tile,
    representative_lonlat,
    verify_sampled_tiles,
)
from huavd_map_build.quality.north.local.tile import VectorTileSamplingGate
from huavd_map_build.quality.south.adapter.process.vector_tile import (
    ProcessVectorTileReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


def feature(properties, coordinates, geometry_type="Point"):
    return {
        "type": "Feature", "properties": properties,
        "geometry": {"type": geometry_type, "coordinates": coordinates},
    }


def decoded_layer(name, properties):
    return {name: {"features": [{"properties": properties}]}}


class MemoryStagedReader:
    def __init__(self, documents) -> None:
        self.documents = documents

    def exists(self, path: str) -> bool:
        return path.rsplit("/", 1)[-1].removesuffix(".geojsonseq") in self.documents

    def features(self, path: str):
        layer = path.rsplit("/", 1)[-1].removesuffix(".geojsonseq")
        yield from enumerate(self.documents.get(layer, ()), 1)


class MemoryTileReader:
    def __init__(self, documents) -> None:
        self.documents = documents
        self.calls = []

    def decode(self, archive, coordinate):
        self.calls.append((archive, coordinate))
        return self.documents.get(coordinate, {})


class TileQualityDomainTest(unittest.TestCase):
    def test_extracts_nested_coordinate_and_converts_web_mercator_tile(self) -> None:
        polygon = feature(
            {"place": "island"}, [[[110.0, 25.0], [111.0, 25.0]]], "Polygon"
        )
        self.assertEqual((110.0, 25.0), representative_lonlat(polygon))
        self.assertEqual(TileCoordinate(10, 512, 512), lonlat_to_tile(0, 0, 10))

    def test_valid_sampled_features_pass(self) -> None:
        island, river = TileCoordinate(10, 824, 438), TileCoordinate(10, 825, 439)
        decoded = {
            island: {
                **decoded_layer("island", {"place": "island"}),
                **decoded_layer("water", {"natural": "water"}),
            },
            river: decoded_layer("waterway", {"waterway": "river", "width": 12}),
        }
        report = verify_sampled_tiles(TileSamplePlan((island,), (river,)), decoded)
        self.assertTrue(report.passed, report.as_dict())

    def test_reports_water_island_missing_island_and_missing_river(self) -> None:
        coordinate = TileCoordinate(10, 824, 438)
        decoded = {coordinate: {
            **decoded_layer("water", {"place": "island"}),
            **decoded_layer("waterway", {"waterway": "canal"}),
        }}
        report = verify_sampled_tiles(
            TileSamplePlan((coordinate,), (coordinate,)), decoded
        )
        codes = {finding.code for finding in report.findings}
        self.assertEqual(
            {"tile-water-island", "tile-island-missing", "tile-river-missing"}, codes
        )


class VectorTileSamplingGateTest(unittest.TestCase):
    def test_plans_samples_from_staged_features_and_decodes_base_archive(self) -> None:
        island_feature = feature(
            {"place": "island"}, [[[110.0, 25.0], [111.0, 25.0]]], "Polygon"
        )
        river_feature = feature(
            {"waterway": "river"}, [[120.2, 35.1], [120.3, 35.2]], "LineString"
        )
        island_tile = lonlat_to_tile(110.0, 25.0, 10)
        river_tile = lonlat_to_tile(120.2, 35.1, 10)
        tiles = MemoryTileReader({
            island_tile: decoded_layer("island", {"place": "island"}),
            river_tile: decoded_layer("waterway", {"waterway": "river"}),
        })
        report = VectorTileSamplingGate(
            MemoryStagedReader({
                "island": (island_feature,), "waterway": (river_feature,),
            }),
            tiles,
        ).verify(
            region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
            workdir="/tmp/maps",
        )
        self.assertTrue(report.passed, report.as_dict())
        self.assertTrue(all(
            archive.endswith("china-guangxi-20261003.base.pmtiles")
            for archive, _coordinate in tiles.calls
        ))

    def test_empty_relevant_layers_are_not_applicable(self) -> None:
        report = VectorTileSamplingGate(
            MemoryStagedReader({"island": (), "waterway": ()}), MemoryTileReader({})
        ).verify(
            region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
            workdir="/tmp/maps",
        )
        self.assertTrue(report.passed)
        self.assertEqual((), report.sampled_tiles)


class ProcessVectorTileReaderTest(unittest.TestCase):
    def test_invokes_pmtiles_with_argument_vector_and_decodes_mvt(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout=b"mvt", stderr=b"")
        decoded = {"waterway": {"features": []}}
        with patch("subprocess.run", return_value=completed) as run, patch(
            "mapbox_vector_tile.decode", return_value=decoded
        ) as decode:
            result = ProcessVectorTileReader().decode(
                "/tmp/map.pmtiles", TileCoordinate(10, 824, 438)
            )
        self.assertEqual(decoded, result)
        run.assert_called_once_with(
            ["pmtiles", "tile", "/tmp/map.pmtiles", "10", "824", "438"],
            capture_output=True,
            check=False,
        )
        decode.assert_called_once_with(b"mvt")

    def test_maps_pmtiles_failure_to_coordinate_error(self) -> None:
        completed = subprocess.CompletedProcess([], 1, stdout=b"", stderr=b"missing")
        with patch("subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "10/824/438.*missing"):
                ProcessVectorTileReader().decode(
                    "/tmp/map.pmtiles", TileCoordinate(10, 824, 438)
                )

    def test_decompresses_gzip_mvt_before_decoding(self) -> None:
        completed = subprocess.CompletedProcess(
            [], 0, stdout=gzip.compress(b"mvt"), stderr=b""
        )
        with patch("subprocess.run", return_value=completed), patch(
            "mapbox_vector_tile.decode", return_value={}
        ) as decode:
            ProcessVectorTileReader().decode(
                "/tmp/map.pmtiles", TileCoordinate(10, 824, 438)
            )
        decode.assert_called_once_with(b"mvt")

    def test_maps_invalid_mvt_to_coordinate_error(self) -> None:
        completed = subprocess.CompletedProcess([], 0, stdout=b"bad", stderr=b"")
        with patch("subprocess.run", return_value=completed), patch(
            "mapbox_vector_tile.decode", side_effect=ValueError("bad protobuf")
        ):
            with self.assertRaisesRegex(RuntimeError, "10/824/438.*bad protobuf"):
                ProcessVectorTileReader().decode(
                    "/tmp/map.pmtiles", TileCoordinate(10, 824, 438)
                )
