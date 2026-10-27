import gzip
import json
from dataclasses import replace
from math import atan, degrees, pi, sinh
from types import SimpleNamespace
import subprocess
import unittest
from copy import deepcopy
from unittest.mock import patch

from huavd_map_build.quality.domain.coverage import (
    CoveragePolicy, RoadCoverageAccumulator, decoded_road_cells, gap_components,
)
from huavd_map_build.quality.domain.tile import TileCoordinate, VectorTilePayload
from huavd_map_build.quality.north.local.tile import VectorTileSamplingGate
from huavd_map_build.quality.south.adapter.process.vector_tile import ProcessVectorTileReader
from huavd_map_build.shared.kernel import BuildDate, RegionId

TILE = TileCoordinate(6, 50, 26)
SESSION = "china-sichuan-20261026"
SETTINGS = {"min_zoom": 6, "max_zoom": 6, "maximum_tile_bytes": 2000,
            "maximum_tile_features": 1000000, "source_layers": ["road"]}
POLICY = CoveragePolicy(zooms=(6,), gap_mode="error")


def lonlat(x, y):
    return [(TILE.x+x/8)/64*360-180,
            degrees(atan(sinh(pi*(1-2*(TILE.y+y/8)/64))))]


def source_line(points=((1.2, 3.5), (6.8, 3.5)), declaration=None):
    return {"type": "Feature", "properties": {"highway": "primary"},
            "geometry": {"type": "LineString", "coordinates": [lonlat(x, y) for x, y in points]},
            "tippecanoe": {"minzoom": 6, "maxzoom": 6} if declaration is None else declaration}


def decoded_line(points=((1.2, 3.5), (6.8, 3.5)), extent=8192):
    return {"road": {"extent": extent, "features": [{"properties": {"highway": "primary"},
            "geometry": {"type": "LineString", "coordinates": [[x/8*extent, (1-y/8)*extent] for x, y in points]}}]}}


class Configuration:
    def __init__(self, mode="error", unlimited=False):
        self.mode, self.unlimited = mode, unlimited

    def tippecanoe(self, *_args):
        return {**SETTINGS, "no_tile_size_limit": self.unlimited}

    def low_zoom_quality(self):
        return {**POLICY.as_dict(), "gap_mode": self.mode}


class Staged:
    def __init__(self, features=None):
        self.documents = [source_line() for _ in range(50)] if features is None else features
        self.scans = 0

    def exists(self, path):
        return path.endswith("/road.geojsonseq")

    def features(self, path):
        self.scans += 1
        yield from enumerate(self.documents, 1)


class Tiles:
    def __init__(self, decoded=None, compressed_bytes=100, uncompressed_bytes=10000):
        self.payload = VectorTilePayload(decoded_line() if decoded is None else decoded, compressed_bytes, uncompressed_bytes)
        self.calls = []

    def read(self, archive, coordinate):
        self.calls.append(coordinate)
        return self.payload


def accumulator(features=None, policy=POLICY):
    builder = RoadCoverageAccumulator(SESSION, SETTINGS, policy)
    for feature in ([source_line() for _ in range(50)] if features is None else features):
        builder.add(feature)
    return builder.finish()


def inspect(staged=None, tiles=None, configuration=None, **kwargs):
    class Headers:
        def read(self, _archive):
            return SimpleNamespace(min_zoom=6, max_zoom=6)
    return VectorTileSamplingGate(
        Staged() if staged is None else staged, Tiles() if tiles is None else tiles,
        Headers(), Configuration() if configuration is None else configuration,
    ).verify(region=RegionId("china/sichuan"), build_date=BuildDate("20261026"),
             workdir="/tmp/maps", **kwargs)


class RoadCoverageDomainTest(unittest.TestCase):
    def test_mixed_road_geometries_only_count_lines_as_expected_coverage(self):
        geometries = [
            {"type": "Point", "coordinates": lonlat(3, 3)},
            {"type": "MultiPoint", "coordinates": [lonlat(3, 3)]},
            {"type": "Polygon", "coordinates": [[lonlat(1, 1), lonlat(6, 1), lonlat(6, 6), lonlat(1, 1)]]},
        ]
        geometries.append({"type": "MultiPolygon", "coordinates": [geometries[-1]["coordinates"]]})
        features = [{**source_line(), "geometry": geometry} for geometry in geometries]
        summary = accumulator([*features, source_line()])
        self.assertEqual(5, summary.road_features)
        self.assertEqual(((6, 1),), summary.eligible_features)
        self.assertEqual(accumulator([source_line()]).samples, summary.samples)
        self.assertEqual(accumulator([source_line()]).audit_points, summary.audit_points)

    def test_decoded_mixed_road_geometries_do_not_cover_missing_lines(self):
        decoded = decoded_line()
        line_cells = decoded_road_cells(decoded)
        non_lines = [
            {"geometry": {"type": "Point", "coordinates": [3000, 3000]}},
            {"geometry": {"type": "Polygon", "coordinates": [[[0, 0], [8192, 0], [8192, 8192], [0, 0]]]}},
            {"geometry": {"type": "MultiPolygon", "coordinates": [[[[0, 0], [8192, 0], [8192, 8192], [0, 0]]]]}},
        ]
        decoded["road"]["features"] = non_lines + decoded["road"]["features"]
        self.assertEqual(line_cells, decoded_road_cells(decoded))
        decoded["road"]["features"] = non_lines
        self.assertEqual(set(), decoded_road_cells(decoded))
        self.assertTrue(gap_components(accumulator().samples[0], decoded_road_cells(decoded), POLICY))

    def test_malformed_road_geometry_still_fails(self):
        for geometry in (None, {"type": "Unknown", "coordinates": []},
                         {"type": "Point", "coordinates": None},
                         {"type": "LineString", "coordinates": [[0, 0]]}):
            with self.subTest(geometry=geometry), self.assertRaises(ValueError):
                accumulator([{**source_line(), "geometry": geometry}])

    def test_crossed_cells_are_covered_without_any_vertex_inside_them(self):
        summary = accumulator([source_line()])
        self.assertEqual((6,), summary.zooms)
        sample = summary.samples[0]
        self.assertEqual(TILE, sample.coordinate)
        self.assertEqual([1]*6, list(sample.counts[3*8+1:3*8+7]))
        self.assertEqual([], list(gap_components(sample, decoded_road_cells(decoded_line()), POLICY)))

    def test_one_source_feature_counts_once_per_cell_even_when_it_reenters(self):
        source = source_line(((1.2, 3.5), (6.8, 3.5), (1.2, 3.5)))
        summary = accumulator([source])
        self.assertEqual(1, max(summary.samples[0].counts))

    def test_partial_missing_region_fails_while_layer_remains_nonempty(self):
        sample = accumulator().samples[0]
        west = decoded_line(((1.2, 3.5), (2.8, 3.5)))
        groups = gap_components(sample, decoded_road_cells(west), POLICY)
        self.assertEqual(((27, 28, 29, 30),), groups)

    def test_zoom_declarations_and_short_lines_do_not_become_expected_coverage(self):
        for source in (source_line(declaration={"minzoom": 7, "maxzoom": 14}),
                       source_line(((1.2, 3.5), (1.201, 3.5)))):
            with self.subTest(source=source):
                summary = accumulator([source])
                self.assertEqual((), summary.samples)
                self.assertEqual(((6, 0),), summary.eligible_features)

    def test_long_polyline_with_short_segments_still_counts(self):
        line = source_line(tuple((1.2+i*.01, 3.5) for i in range(560)))
        self.assertEqual(1, accumulator([line]).eligible_features[0][1])

    def test_cross_tile_and_antimeridian_lines_are_not_assigned_only_to_first_tile(self):
        summary = accumulator([source_line(((7.5, 3.5), (8.5, 3.5)))])
        self.assertEqual({50, 51}, {s.coordinate.x for s in summary.samples})
        source = source_line()
        source["geometry"]["coordinates"] = [[179.9, 0], [-179.9, 0]]
        summary = accumulator([source])
        self.assertEqual({0, 63}, {s.coordinate.x for s in summary.samples})

    def test_multilines_and_decoder_extent_and_y_direction(self):
        source = source_line()
        source["geometry"] = {"type": "MultiLineString", "coordinates": [source["geometry"]["coordinates"]]}
        for extent in (4096, 8192):
            self.assertTrue(set(range(25, 31)).issubset(decoded_road_cells(decoded_line(extent=extent))))
        self.assertEqual(1, accumulator([source]).road_features)

    def test_buffer_only_lines_do_not_fill_tile_interior(self):
        self.assertEqual(set(), decoded_road_cells(decoded_line(((-2, 2), (-1, 6)))))
        self.assertTrue(all(cell % 8 == 0 for cell in decoded_road_cells(decoded_line(((-2, 3.5), (.5, 3.5))))))

    def test_sparse_sources_and_tile_edges_do_not_trigger_gap(self):
        sample = accumulator([source_line()]).samples[0]
        self.assertEqual((), gap_components(sample, set(), POLICY))
        edge = accumulator([source_line(((.2, .5), (6.8, .5))) for _ in range(50)]).samples[0]
        self.assertEqual((), gap_components(edge, set(), POLICY))

    def test_policy_validation_and_deterministic_bounded_sample_selection(self):
        for changed in ({"zooms": [True]}, {"zooms": [[6]]}, {"zooms": [6, 6]},
                        {"gap_mode": "ignore"}, {"samples_per_zoom": 9},
                        {"minimum_gap_cells": 0}, {"minimum_line_pixels": float("nan")}):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                CoveragePolicy.from_settings({**POLICY.as_dict(), **changed})
        summary = accumulator([source_line(((i*8+1.2, 3.5), (i*8+6.8, 3.5))) for i in range(10)])
        self.assertEqual(8, len(summary.samples))
        self.assertEqual(summary.as_dict(), json.loads(json.dumps(summary.as_dict())))


class LowZoomGateTest(unittest.TestCase):
    def test_mixed_source_and_tile_geometries_pass_without_hiding_line_gaps(self):
        source = {**source_line(), "geometry": {"type": "Point", "coordinates": lonlat(3, 3)}}
        decoded = decoded_line()
        decoded["road"]["features"].insert(0, deepcopy(source))
        report = inspect(staged=Staged([source] + [source_line() for _ in range(50)]), tiles=Tiles(decoded))
        self.assertTrue(report.passed, report.as_dict())
        self.assertEqual(51, report.coverage_audit["source_road_features"])

    def test_partial_gap_fails_in_error_mode_and_is_visible_in_report_mode(self):
        west = Tiles(decoded_line(((1.2, 3.5), (2.8, 3.5))))
        failed = inspect(tiles=west)
        self.assertIn("tile-low-zoom-gap", [f.code for f in failed.findings])
        diagnostic = inspect(tiles=west, configuration=Configuration("report"))
        self.assertTrue(diagnostic.passed, diagnostic.as_dict())
        self.assertEqual("gaps", diagnostic.coverage_audit["status"])
        self.assertEqual("tile-low-zoom-gap", diagnostic.coverage_audit["diagnostics"][0]["code"])

    def test_full_spatial_recovery_passes_and_all_sample_decodes_are_cached(self):
        tiles = Tiles()
        report = inspect(tiles=tiles)
        self.assertTrue(report.passed, report.as_dict())
        self.assertEqual([TILE], tiles.calls)
        self.assertEqual(10000, report.coverage_audit["samples"][0]["uncompressed_bytes"])

    def test_precomputed_summary_avoids_a_second_road_scan(self):
        source = Staged()
        report = inspect(staged=source, source_coverage=accumulator())
        self.assertTrue(report.passed, report.as_dict())
        self.assertEqual(0, source.scans)

    def test_stale_session_or_policy_summary_fails(self):
        for summary in (replace(accumulator(), session="other"),
                        replace(accumulator(), policy=replace(POLICY, minimum_source_features=100))):
            with self.subTest(summary=summary):
                report = inspect(source_coverage=summary)
                self.assertIn("tile-low-zoom-source", [f.code for f in report.findings])

    def test_compressed_budget_is_independent_of_uncompressed_size(self):
        self.assertTrue(inspect(tiles=Tiles(uncompressed_bytes=1000000)).passed)
        failed = inspect(tiles=Tiles(compressed_bytes=2001))
        self.assertIn("tile-low-zoom-oversize", [f.code for f in failed.findings])
        self.assertTrue(inspect(tiles=Tiles(compressed_bytes=2001), configuration=Configuration(unlimited=True)).passed)

    def test_missing_decode_failure_and_missing_source_fail_even_in_report_mode(self):
        report = inspect(tiles=Tiles({}, 0, 0), configuration=Configuration("report"))
        self.assertIn("tile-low-zoom-missing", [f.code for f in report.findings])
        class BadTiles:
            def read(self, *_args):
                raise ValueError("bad payload")
        report = inspect(tiles=BadTiles())
        self.assertIn("tile-low-zoom-decode", [f.code for f in report.findings])
        staged = Staged()
        staged.exists = lambda _path: False
        report = inspect(staged=staged)
        self.assertIn("tile-low-zoom-source", [f.code for f in report.findings])

    def test_no_low_zoom_samples_has_explicit_reason(self):
        report = inspect(staged=Staged([]))
        self.assertTrue(report.passed)
        self.assertEqual("no-low-zoom-samples", report.coverage_audit["status"])
        self.assertTrue(report.coverage_audit["reason"])

    def test_subpixel_and_zoom_filtered_roads_do_not_require_a_highest_zoom_tile(self):
        for source in (source_line(((1.2, 3.5), (1.201, 3.5))),
                       source_line(declaration={"minzoom": 7, "maxzoom": 14})):
            with self.subTest(source=source):
                tiles = Tiles({}, 0, 0)
                report = inspect(staged=Staged([source]), tiles=tiles)
                self.assertTrue(report.passed, report.as_dict())
                self.assertEqual([], tiles.calls)


class TilePayloadReaderTest(unittest.TestCase):
    def test_real_mvt_roundtrip_catches_partial_hole_and_accepts_recovery(self):
        import mapbox_vector_tile
        for points, passed in ((((1.2, 3.5), (2.8, 3.5)), False),
                               (((1.2, 3.5), (6.8, 3.5)), True)):
            layer = decoded_line(points)["road"]
            raw = mapbox_vector_tile.encode({"name": "road", "features": layer["features"]},
                                            default_options={"extents": layer["extent"]})
            completed = subprocess.CompletedProcess([], 0, stdout=gzip.compress(raw), stderr=b"")
            with self.subTest(passed=passed), patch("subprocess.run", return_value=completed) as process:
                report = inspect(tiles=ProcessVectorTileReader())
            self.assertEqual(passed, report.passed, report.as_dict())
            process.assert_called_once()

    def test_reader_retains_original_compressed_size_and_missing_payload(self):
        raw = gzip.compress(b"mvt" * 100)
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=raw, stderr=b"")), patch(
            "mapbox_vector_tile.decode", return_value=decoded_line()
        ):
            payload = ProcessVectorTileReader().read("/tmp/map.pmtiles", TILE)
        self.assertEqual(len(raw), payload.compressed_bytes)
        self.assertEqual(300, payload.uncompressed_bytes)
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")):
            self.assertEqual(VectorTilePayload({}, 0, 0), ProcessVectorTileReader().read("/tmp/map.pmtiles", TILE))

    def test_truncated_gzip_is_a_coordinate_error(self):
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"\x1f\x8b", stderr=b"")):
            with self.assertRaisesRegex(RuntimeError, "6/50/26"):
                ProcessVectorTileReader().read("/tmp/map.pmtiles", TILE)
