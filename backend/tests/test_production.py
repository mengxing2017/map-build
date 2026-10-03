import unittest
from pathlib import Path

from huavd_map_build.bootstrap import build_planner, repository_root
from huavd_map_build.shared.kernel import BuildDate, RegionId


class BuildPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner = build_planner(repository_root(Path(__file__)))

    def test_default_input_preserves_manual_download_workflow(self) -> None:
        plan = self.planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20260818"),
            role="base_raster",
            workdir=Path("/tmp/maps"),
        )
        self.assertEqual(
            "/tmp/maps/mirror/guangxi-latest.osm.pbf", plan.input_path
        )
        self.assertEqual(["base", "raster_bake"], [role.value for role in plan.roles])

    def test_explicit_absolute_input_is_not_rewritten(self) -> None:
        explicit = Path("/data/manual/custom.osm.pbf")
        plan = self.planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20260818"),
            role="base",
            workdir=Path("/tmp/maps"),
            input_path=explicit,
        )
        self.assertEqual(str(explicit), plan.input_path)
