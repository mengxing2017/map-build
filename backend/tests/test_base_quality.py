import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    base_build_executor,
    build_planner,
    repository_root,
)
from huavd_map_build.quality.domain.base import BaseDeepQualityError
from huavd_map_build.quality.domain.staging import (
    BaseStagingQualityReport,
    StagingFinding,
)
from huavd_map_build.quality.domain.tile import (
    TileCoordinate,
    TileSamplingReport,
)
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.quality.north.local.base import BaseDeepQualityGate
from huavd_map_build.shared.kernel import BuildDate, RegionId


class StubStagingGate:
    def __init__(self, report) -> None:
        self.report = report
        self.calls = []

    def inspect(self, build):
        self.calls.append(build)
        return self.report


class StubTileGate:
    def __init__(self, report) -> None:
        self.report = report
        self.calls = []

    def verify(self, **kwargs):
        self.calls.append(kwargs)
        return self.report


class BaseDeepQualityGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.build = build_planner(root).plan(
            region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
            role="base", workdir=Path("/tmp/maps"),
        )

    def test_combines_staging_and_tile_reports(self) -> None:
        staging = StubStagingGate(BaseStagingQualityReport(("road",), 1, ()))
        tiles = StubTileGate(TileSamplingReport((TileCoordinate(10, 1, 2),), ()))
        report = BaseDeepQualityGate(staging, tiles).inspect(self.build)
        self.assertTrue(report.passed)
        self.assertEqual([self.build], staging.calls)
        self.assertEqual({
            "region": self.build.region,
            "build_date": self.build.build_date,
            "workdir": "/tmp/maps",
        }, tiles.calls[0])

    def test_production_base_executor_uses_combined_deep_gate(self) -> None:
        executor = base_build_executor(repository_root(Path(__file__)))
        self.assertIsInstance(executor._deep_verifier, BaseDeepQualityGate)

    def test_aggregates_both_failures_before_raising(self) -> None:
        staging = StubStagingGate(BaseStagingQualityReport(
            ("road",), 0, (StagingFinding("staging", "road", "bad"),)
        ))
        tiles = StubTileGate(TileSamplingReport(
            (), (QualityFinding("tile", "bad"),)
        ))
        gate = BaseDeepQualityGate(staging, tiles)
        with self.assertRaises(BaseDeepQualityError) as raised:
            gate.verify(self.build)
        self.assertEqual(1, len(raised.exception.report.staging.findings))
        self.assertEqual(1, len(raised.exception.report.tiles.findings))
        self.assertEqual(1, len(tiles.calls))
