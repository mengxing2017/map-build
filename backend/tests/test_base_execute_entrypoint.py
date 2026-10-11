import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

from huavd_map_build import cli
from huavd_map_build.production.domain.orchestration import BuildJob, BuildStatus
from huavd_map_build.production.north.local.execution import BuildExecutionError
from huavd_map_build.quality.domain.base import BaseDeepQualityError


class StubExecutionService:
    def __init__(self, job: BuildJob, failure: Exception | None = None) -> None:
        self.job = job
        self.failure = failure
        self.plans = []

    def run(self, plan):
        self.plans.append(plan)
        if self.failure is not None:
            raise BuildExecutionError(self.job, self.failure)
        return self.job


class ExecuteBaseEntrypointTest(unittest.TestCase):
    def invoke(self, workdir: Path, service: StubExecutionService, *extra: str):
        output = io.StringIO()
        arguments = [
            "build", "execute-base", "--region", "china/guangxi",
            "--yyyymmdd", "20261003", "--workdir", str(workdir), *extra,
        ]
        with patch.object(cli, "vector_build_execution_service", return_value=service):
            with redirect_stdout(output):
                status = cli.run(arguments)
        return status, json.loads(output.getvalue())

    def test_runs_base_plan_and_emits_successful_job(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            status, document = self.invoke(Path(temporary), service)
        self.assertEqual(0, status)
        self.assertEqual("succeeded", document["status"])
        self.assertEqual(("base",), tuple(
            role.value for role in service.plans[0].build.roles
        ))
        self.assertEqual(
            str(Path(temporary) / "mirror" / "guangxi-latest.osm.pbf"),
            service.plans[0].build.input_path,
        )

    def test_preserves_explicit_manual_input_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manual = Path(temporary) / "downloads" / "map.osm.pbf"
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            self.invoke(Path(temporary), service, "--input", str(manual))
        self.assertEqual(str(manual), service.plans[0].build.input_path)

    def test_glyph_flag_adds_resource_and_quality_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            self.invoke(Path(temporary), service, "--glyph", "1")
        self.assertEqual(
            ["glyph", "sprite", "style", "style-quality"],
            [stage.id for stage in service.plans[0].stages][-4:],
        )

    def test_execute_vector_runs_forced_building_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            output = io.StringIO()
            arguments = [
                "build", "execute-vector", "--region", "china/guangxi",
                "--yyyymmdd", "20261003", "--role", "building",
                "--workdir", temporary, "--force-building",
            ]
            with patch.object(
                cli, "vector_build_execution_service", return_value=service
            ), redirect_stdout(output):
                status = cli.run(arguments)
        self.assertEqual(0, status)
        self.assertEqual(("building",), tuple(
            role.value for role in service.plans[0].build.roles
        ))
        self.assertEqual(
            ["tippecanoe:building", "finalize-vector:building"],
            [stage.id for stage in service.plans[0].stages][-2:],
        )

    def test_execute_vector_both_skips_or_forces_optional_building(self) -> None:
        for force, expected_roles in ((False, ("base",)), (True, ("base", "building"))):
            with self.subTest(force=force), tempfile.TemporaryDirectory() as temporary:
                service = StubExecutionService(BuildJob(
                    "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
                ))
                arguments = [
                    "build", "execute-vector", "--region", "china/guangxi",
                    "--yyyymmdd", "20261003", "--role", "both",
                    "--workdir", temporary,
                ]
                if force:
                    arguments.append("--force-building")
                with patch.object(
                    cli, "vector_build_execution_service", return_value=service
                ), redirect_stdout(io.StringIO()):
                    status = cli.run(arguments)
                self.assertEqual(0, status)
                self.assertEqual(expected_roles, tuple(
                    role.value for role in service.plans[0].build.roles
                ))

    def test_emits_failed_job_and_returns_quality_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            failed = BuildJob(
                "china-guangxi-20261003", (), BuildStatus.FAILED
            )
            service = StubExecutionService(failed, RuntimeError("stage failed"))
            status, document = self.invoke(Path(temporary), service)
        self.assertEqual(1, status)
        self.assertEqual("failed", document["status"])

    def test_missing_input_failure_uses_shell_compatible_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            failed = BuildJob(
                "china-guangxi-20261003", (), BuildStatus.FAILED
            )
            service = StubExecutionService(failed, ValueError("missing input"))
            status, document = self.invoke(Path(temporary), service)
        self.assertEqual(2, status)
        self.assertEqual("failed", document["status"])

    def test_deep_quality_failure_includes_detailed_report(self) -> None:
        details = {"status": "failed", "tiles": {"findings": [
            {"code": "tile-decode", "detail": "cannot decode 10/818/448"}
        ]}}
        report = Mock()
        report.as_dict.return_value = details
        with tempfile.TemporaryDirectory() as temporary:
            service = StubExecutionService(
                BuildJob("china-guangxi-20261003", (), BuildStatus.FAILED),
                BaseDeepQualityError(report),
            )
            status, document = self.invoke(Path(temporary), service)
        self.assertEqual(3, status)
        self.assertEqual(details, document["quality"])

    def test_removes_existing_partial_artifact_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            output = (
                workdir / "outputs"
                / "china-guangxi-20261003.base.manifest.json"
            )
            output.parent.mkdir()
            output.touch()
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            status, _document = self.invoke(workdir, service)
            self.assertFalse(output.exists())
        self.assertEqual(0, status)
        self.assertEqual(1, len(service.plans))

    def test_complete_artifacts_require_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workdir = Path(temporary)
            prefix = workdir / "outputs" / "china-guangxi-20261003.base"
            paths = (
                prefix.with_suffix(".base.pmtiles"),
                prefix.with_suffix(".base.pmtiles.sha512"),
                prefix.with_suffix(".base.manifest.json"),
                prefix.with_suffix(".base.attribution.json"),
            )
            for output in paths:
                output.parent.mkdir(exist_ok=True)
                output.touch()
            service = StubExecutionService(BuildJob(
                "china-guangxi-20261003", (), BuildStatus.SUCCEEDED
            ))
            with self.assertRaisesRegex(RuntimeError, "pass --force"):
                self.invoke(workdir, service)
            self.assertEqual([], service.plans)
            status, _document = self.invoke(workdir, service, "--force")
        self.assertEqual(0, status)
        self.assertEqual(1, len(service.plans))
