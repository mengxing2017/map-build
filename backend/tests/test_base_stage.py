import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    build_orchestration_planner,
    build_planner,
    repository_root,
)
from huavd_map_build.production.domain.orchestration import BuildStatus
from huavd_map_build.production.north.local.base_stage import BaseBuildStageExecutor
from huavd_map_build.production.north.local.execution import (
    BuildExecutionError,
    BuildExecutionService,
)
from huavd_map_build.quality.domain.base import BaseDeepQualityError, BaseDeepQualityReport
from huavd_map_build.quality.domain.staging import BaseStagingQualityReport, StagingFinding
from huavd_map_build.quality.domain.tile import TileSamplingReport
from huavd_map_build.production.south.adapter.workspace.build_source import (
    FileSystemBuildSourceWorkspace,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class RecordingService:
    def __init__(self, name: str, calls: list[tuple[str, object]]) -> None:
        self.name, self.calls = name, calls

    def run(self, request):
        self.calls.append((self.name, request))
        return None


class FinalizationResult:
    def __init__(self, passed: bool) -> None:
        self.passed = passed


class RecordingFinalizer(RecordingService):
    def __init__(self, calls, passed: bool = True) -> None:
        super().__init__("finalize-vector", calls)
        self.passed = passed

    def run(self, request):
        super().run(request)
        return FinalizationResult(self.passed)


class RecordingSource:
    def __init__(self, calls) -> None:
        self.calls = calls

    def link(self, input_path: str, workdir: str, session: str) -> str:
        self.calls.append(("source-link", (input_path, workdir, session)))
        return f"{workdir}/staging/{session}/source.osm.pbf"


class RecordingDeepVerifier:
    def __init__(self, calls) -> None:
        self.calls = calls

    def verify(self, build) -> None:
        self.calls.append(("deep-verify", build))


class StyleQualityResult:
    def __init__(self, passed=True) -> None:
        self.passed = passed
        self.findings = () if passed else ("bad",)


class RecordingStyleQuality:
    def __init__(self, calls, passed=True) -> None:
        self.calls, self.passed = calls, passed

    def verify(self, **request):
        self.calls.append(("style-quality", request))
        return StyleQualityResult(self.passed)


class FileSystemBuildSourceWorkspaceTest(unittest.TestCase):
    def test_links_manual_input_into_canonical_session_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "manual/custom.osm.pbf"
            source.parent.mkdir()
            source.write_bytes(b"pbf")
            target = FileSystemBuildSourceWorkspace().link(
                str(source), directory, "china-guangxi-20261003"
            )
            linked = Path(target)
            self.assertTrue(linked.is_symlink())
            self.assertEqual(source.resolve(), linked.resolve())

    def test_rejects_missing_input_before_creating_staging(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "does not exist"):
                FileSystemBuildSourceWorkspace().link(
                    "missing.osm.pbf", directory, "china-guangxi-20261003"
                )
            self.assertFalse(Path(directory, "staging").exists())


class BaseBuildStageExecutorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.configuration = build_configuration_service(cls.root)
        build = build_planner(cls.root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="base",
            workdir=Path("/tmp/maps"),
        )
        cls.plan = build_orchestration_planner(cls.root).plan(build, glyph=False)

    def executor(
        self, calls, finalizer_passed: bool = True,
        style_quality_passed: bool = True,
    ):
        service = lambda name: RecordingService(name, calls)
        return BaseBuildStageExecutor(
            self.configuration, RecordingSource(calls), service("tags-filter"),
            service("export"), service("normalize"), service("place-admin-enrich"),
            service("island-water-flag"), service("island-anchor"),
            service("admin-line-tier"), service("profile-transform"),
            service("tippecanoe"), RecordingFinalizer(calls, finalizer_passed),
            RecordingDeepVerifier(calls),
            service("glyph"), service("sprite"), service("style"),
            RecordingStyleQuality(calls, style_quality_passed),
        )

    def test_dispatches_complete_base_plan_to_python_services(self) -> None:
        calls: list[tuple[str, object]] = []
        job = BuildExecutionService(self.executor(calls), lambda: "now").run(self.plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertEqual(
            [stage.id.split(":", 1)[0] for stage in self.plan.stages],
            [name for name, _request in calls],
        )
        tags_request = next(request for name, request in calls if name == "tags-filter")
        expected_layers = self.configuration.tippecanoe(
            "china/guangxi", "base"
        )["source_layers"]
        self.assertEqual(",".join(expected_layers), tags_request.layers)
        self.assertEqual(
            "/tmp/maps/staging/china-guangxi-20261003/source.osm.pbf",
            tags_request.input_path,
        )

    def test_failed_finalizer_prevents_deep_verification(self) -> None:
        calls: list[tuple[str, object]] = []
        with self.assertRaises(BuildExecutionError) as raised:
            BuildExecutionService(
                self.executor(calls, finalizer_passed=False), lambda: "now"
            ).run(self.plan)
        self.assertEqual("finalize-vector:base", raised.exception.job.events[-1].stage)
        self.assertNotIn("deep-verify", [name for name, _request in calls])

    def test_dispatches_building_layers_and_role_without_base_deep_gate(self) -> None:
        build = build_planner(self.root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="building",
            workdir=Path("/tmp/maps"),
        )
        plan = build_orchestration_planner(self.root).plan(
            build, glyph=False, force_building=True
        )
        calls: list[tuple[str, object]] = []
        job = BuildExecutionService(self.executor(calls), lambda: "now").run(plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertNotIn("deep-verify", [name for name, _request in calls])
        tags_request = next(request for name, request in calls if name == "tags-filter")
        self.assertEqual("building", tags_request.layers)
        tile_request = next(request for name, request in calls if name == "tippecanoe")
        finalize_request = next(
            request for name, request in calls if name == "finalize-vector"
        )
        self.assertIs(Role.BUILDING, tile_request.role)
        self.assertIs(Role.BUILDING, finalize_request.role)

    def test_combined_build_shares_preprocessing_and_finalizes_each_role(self) -> None:
        build = build_planner(self.root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="both",
            workdir=Path("/tmp/maps"),
        )
        plan = build_orchestration_planner(self.root).plan(
            build, glyph=False, force_building=True
        )
        calls: list[tuple[str, object]] = []
        job = BuildExecutionService(self.executor(calls), lambda: "now").run(plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertEqual(1, sum(name == "tags-filter" for name, _ in calls))
        tags_request = next(request for name, request in calls if name == "tags-filter")
        expected = list(self.configuration.tippecanoe(
            "china/guangxi", "base"
        )["source_layers"])
        for layer in self.configuration.tippecanoe(
            "china/guangxi", "building"
        )["source_layers"]:
            if layer not in expected:
                expected.append(layer)
        self.assertEqual(",".join(expected), tags_request.layers)
        finalized = [
            request.role for name, request in calls if name == "finalize-vector"
        ]
        self.assertEqual([Role.BASE, Role.BUILDING], finalized)
        deep_build = next(request for name, request in calls if name == "deep-verify")
        self.assertEqual((Role.BASE,), deep_build.roles)

    def test_dispatches_glyph_sprite_style_and_quality_in_order(self) -> None:
        build = build_planner(self.root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="base",
            workdir=Path("/tmp/maps"),
        )
        plan = build_orchestration_planner(self.root).plan(build, glyph=True)
        calls: list[tuple[str, object]] = []
        job = BuildExecutionService(self.executor(calls), lambda: "now").run(plan)
        self.assertEqual(BuildStatus.SUCCEEDED, job.status)
        self.assertEqual(
            ["glyph", "sprite", "style", "style-quality"],
            [name for name, _request in calls][-4:],
        )
        glyph_request = calls[-4][1]
        sprite_request = calls[-3][1]
        self.assertTrue(glyph_request.force)
        self.assertTrue(sprite_request.force)

    def test_style_quality_failure_is_terminal(self) -> None:
        build = build_planner(self.root).plan(
            region=RegionId("china/guangxi"),
            build_date=BuildDate("20261003"), role="base",
            workdir=Path("/tmp/maps"),
        )
        plan = build_orchestration_planner(self.root).plan(build, glyph=True)
        with self.assertRaises(BuildExecutionError) as raised:
            BuildExecutionService(
                self.executor([], style_quality_passed=False), lambda: "now"
            ).run(plan)
        self.assertEqual("style-quality", raised.exception.job.events[-1].stage)

    def test_writes_deep_quality_report_before_reraising(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            build = build_planner(self.root).plan(
                region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
                role="base", workdir=Path(directory),
            )
            error = BaseDeepQualityError(BaseDeepQualityReport(
                BaseStagingQualityReport(
                    (), 0, (StagingFinding("place-name-tier", "place_label", "bad"),)
                ), TileSamplingReport((), ()),
            ))
            BaseBuildStageExecutor._write_deep_quality_report(build, error)
            path = Path(directory) / "staging" / build.session.value / "quality" / "base-deep.json"
            document = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual("failed", document["status"])
        self.assertEqual("place-name-tier", document["staging"]["findings"][0]["code"])
