import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_orchestration_planner,
    build_planner,
    repository_root,
)
from huavd_map_build.production.domain.orchestration import BuildStatus, StageStatus
from huavd_map_build.production.north.local.execution import (
    BuildExecutionError,
    BuildExecutionService,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class RecordingStageExecutor:
    def __init__(self, failure_stage: str | None = None) -> None:
        self.calls: list[str] = []
        self.failure_stage = failure_stage

    def execute(self, stage_id, build) -> None:
        self.calls.append(stage_id)
        if stage_id == self.failure_stage:
            raise RuntimeError("fixture stage failure")


class SequenceClock:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> str:
        self.value += 1
        return f"t{self.value}"


class BuildExecutionServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.planner = build_planner(root)
        cls.orchestration = build_orchestration_planner(root)

    def plan(self, role: str = "base", force_building: bool = False):
        build = self.planner.plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"),
            role=role,
            workdir=Path("/tmp/maps"),
        )
        return self.orchestration.plan(
            build, glyph=role == "raster_bake", force_building=force_building
        )

    def test_executes_base_stages_in_plan_order_and_records_events(self) -> None:
        plan = self.plan()
        executor = RecordingStageExecutor()
        job = BuildExecutionService(executor, SequenceClock()).run(plan)
        expected = [stage.id for stage in plan.stages]
        self.assertEqual(expected, executor.calls)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertTrue(all(
            stage.status is StageStatus.SUCCEEDED for stage in job.stages
        ))
        self.assertEqual("BuildPlanned", job.events[0].type)
        self.assertEqual("BuildSucceeded", job.events[-1].type)
        document = job.as_dict()
        self.assertEqual("succeeded", document["status"])
        self.assertEqual(expected[0], document["stages"][0]["id"])
        self.assertEqual("BuildPlanned", document["events"][0]["type"])
        self.assertEqual(
            list(range(1, len(job.events) + 1)),
            [event.sequence for event in job.events],
        )

    def test_reports_each_stage_start_and_completion_in_order(self) -> None:
        plan = self.plan()
        reports = []
        BuildExecutionService(
            RecordingStageExecutor(), SequenceClock(),
            lambda status, stage, index, total: reports.append(
                (status, stage, index, total)
            ),
        ).run(plan)
        expected = []
        for index, stage in enumerate(plan.stages, 1):
            expected.extend((
                ("start", stage.id, index, len(plan.stages)),
                ("done", stage.id, index, len(plan.stages)),
            ))
        self.assertEqual(expected, reports)

    def test_failure_exposes_terminal_job_and_preserves_original_cause(self) -> None:
        plan = self.plan()
        failed_stage = plan.stages[2].id
        executor = RecordingStageExecutor(failed_stage)
        with self.assertRaises(BuildExecutionError) as raised:
            BuildExecutionService(executor, SequenceClock()).run(plan)
        error = raised.exception
        self.assertIsInstance(error.cause, RuntimeError)
        self.assertEqual(BuildStatus.FAILED, error.job.status)
        self.assertEqual(failed_stage, error.job.events[-1].stage)
        self.assertEqual("BuildFailed", error.job.events[-1].type)
        self.assertEqual("fixture stage failure", error.job.events[-1].message)
        self.assertEqual(
            [stage.id for stage in plan.stages[:3]], executor.calls
        )
        self.assertTrue(all(
            stage.status is StageStatus.PENDING for stage in error.job.stages[3:]
        ))

    def test_rejects_non_vector_plan_before_running_any_stage(self) -> None:
        plan = self.plan("raster_bake")
        executor = RecordingStageExecutor()
        with self.assertRaisesRegex(ValueError, "base/building roles"):
            BuildExecutionService(executor, SequenceClock()).run(plan)
        self.assertEqual([], executor.calls)

    def test_executes_building_stages(self) -> None:
        plan = self.plan("building", force_building=True)
        executor = RecordingStageExecutor()
        job = BuildExecutionService(executor, SequenceClock()).run(plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertEqual([stage.id for stage in plan.stages], executor.calls)

    def test_executes_combined_vector_stages(self) -> None:
        plan = self.plan("both", force_building=True)
        executor = RecordingStageExecutor()
        job = BuildExecutionService(executor, SequenceClock()).run(plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertIn("finalize-vector:base", executor.calls)
        self.assertIn("finalize-vector:building", executor.calls)
        self.assertEqual(1, executor.calls.count("source-link"))

    def test_plan_uses_unified_finalizer_before_deep_verification(self) -> None:
        stages = [stage.id for stage in self.plan().stages]
        self.assertEqual(
            ["tippecanoe:base", "finalize-vector:base", "deep-verify:base"],
            stages[-3:],
        )
