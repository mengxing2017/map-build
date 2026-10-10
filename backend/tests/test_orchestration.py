from local_extract_fixture import local_extract_repository
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_orchestration_planner,
    build_planner,
    repository_root,
)
from huavd_map_build.production.domain.orchestration import (
    BuildJob,
    BuildStatus,
    StageStatus,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class BuildOrchestrationPlannerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.build_planner = build_planner(root)
        cls.orchestration = build_orchestration_planner(root)

    def plan(self, role: str, glyph: bool = False):
        build = self.build_planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role=role,
            workdir=Path("/tmp/maps"),
        )
        return self.orchestration.plan(build, glyph)

    def test_base_plan_preserves_manual_input_and_stage_order(self) -> None:
        plan = self.plan("base")
        self.assertEqual(
            "/tmp/maps/mirror/guangxi-latest.osm.pbf", plan.build.input_path
        )
        stages = [stage.id for stage in plan.stages]
        self.assertEqual(
            ["source-link", "tags-filter", "export", "normalize"], stages[:4]
        )
        self.assertLess(stages.index("place-admin-enrich"), stages.index("tippecanoe:base"))
        self.assertEqual(
            ["tippecanoe:base", "finalize-vector:base", "deep-verify:base"],
            stages[-3:],
        )

    def test_raster_plan_requires_glyph_and_supports_existing_base(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires glyph"):
            self.plan("raster_bake")
        stages = [stage.id for stage in self.plan("raster_bake", True).stages]
        self.assertEqual("verify-existing-base", stages[0])
        self.assertEqual(
            ["glyph", "sprite", "style", "style-quality", "raster-bake"],
            stages[-5:],
        )

    def test_both_skips_unconfigured_building_and_filters_output(self) -> None:
        plan = self.plan("both")
        self.assertEqual(["base"], [role.value for role in plan.build.roles])
        self.assertEqual(["building"], [role.value for role in plan.skipped_roles])
        self.assertEqual(1, len(plan.build.output_paths))
        with self.assertRaisesRegex(ValueError, "building role is not enabled"):
            self.plan("building")
        with self.assertRaisesRegex(ValueError, "separate DEM"):
            self.plan("dem")

    def test_forced_building_has_role_specific_terminal_stages(self) -> None:
        build = self.build_planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="building",
            workdir=Path("/tmp/maps"),
        )
        plan = self.orchestration.plan(build, glyph=False, force_building=True)
        stages = [stage.id for stage in plan.stages]
        self.assertEqual(
            ["tippecanoe:building", "finalize-vector:building"], stages[-2:]
        )
        self.assertNotIn("deep-verify:base", stages)


class BuildJobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.build_planner = build_planner(root)
        cls.orchestration = build_orchestration_planner(root)

    def plan(self, role: str, glyph: bool = False):
        build = self.build_planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role=role,
            workdir=Path("/tmp/maps"),
        )
        return self.orchestration.plan(build, glyph)

    def test_successful_transitions_emit_monotonic_events(self) -> None:
        plan = self.plan("raster_bake", True)
        job = BuildJob.from_plan(plan, "2026-10-03T00:00:00Z")
        while job.status is not BuildStatus.SUCCEEDED:
            job = job.start_next("2026-10-03T00:00:01Z")
            job = job.complete_current("2026-10-03T00:00:02Z")
        self.assertTrue(all(
            stage.status is StageStatus.SUCCEEDED for stage in job.stages
        ))
        self.assertEqual(
            list(range(1, len(job.events) + 1)),
            [event.sequence for event in job.events],
        )
        self.assertEqual("BuildSucceeded", job.events[-1].type)
        self.assertEqual("StageCompleted", job.events[-2].type)

    def test_failure_is_terminal_and_records_message(self) -> None:
        plan = self.plan("base")
        job = BuildJob.from_plan(plan, "t0").start_next("t1")
        job = job.fail_current("t2", "osmium failed")
        self.assertEqual(BuildStatus.FAILED, job.status)
        self.assertEqual("osmium failed", job.events[-1].message)
        with self.assertRaisesRegex(ValueError, "cannot start"):
            job.start_next("t3")


class HighDetailStageOrderTest(unittest.TestCase):
    def test_zoom_policy_precedes_water_derivation(self):
        from huavd_map_build.bootstrap import build_planner, repository_root
        from pathlib import Path
        from huavd_map_build.shared.kernel import BuildDate, RegionId
        from huavd_map_build.production.domain.orchestration import create_execution_plan
        fixture_root = self.enterContext(local_extract_repository(repository_root(Path(__file__))))
        build = build_planner(fixture_root).plan(
            region=RegionId("china/guangxi/test-extract"), build_date=BuildDate("20261003"),
            role="base", workdir=Path("/tmp/maps"), input_path=Path("/tmp/source.osm.pbf"))
        plan = create_execution_plan(build, ("road", "water", "island", "admin_line", "place_label"), False, True, ())
        stages = [stage.id for stage in plan.stages]
        self.assertLess(stages.index("admin-line-tier"), stages.index("profile-transform"))
        self.assertLess(stages.index("profile-transform"), stages.index("island-water-flag"))
