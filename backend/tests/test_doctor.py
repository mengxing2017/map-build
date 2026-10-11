import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path
from tempfile import TemporaryDirectory

from huavd_map_build.quality.domain.doctor import (
    ToolHealth,
    ToolStatus,
)
from huavd_map_build.quality.north.local.doctor import DoctorQuery
from huavd_map_build.quality.south.adapter.process.tool_probe import ProcessToolProbe
from huavd_map_build import cli


class _CatalogStub:
    def validate(self):
        return type("Summary", (), {"schema_version": "1", "region_count": 2})()


class _InvalidCatalogStub:
    def validate(self):
        raise ValueError("invalid catalog")


class _ToolProbeStub:
    def __init__(self, missing: str | None = None) -> None:
        self._missing = missing

    def probe(self, requirement):
        if requirement.name == self._missing:
            return ToolStatus(requirement.name, ToolHealth.MISSING)
        return ToolStatus(requirement.name, ToolHealth.OK, "v1", f"/bin/{requirement.name}")


class DoctorQueryTest(unittest.TestCase):
    def test_strict_cli_rejects_unavailable_dependencies(self) -> None:
        query = DoctorQuery(_ToolProbeStub("mvt-decode"), _CatalogStub())
        with patch.object(cli, "doctor_query", return_value=query), redirect_stdout(io.StringIO()):
            self.assertEqual(0, cli.run(["doctor"]))
            self.assertEqual(3, cli.run(["doctor", "--strict"]))

    def test_all_required_tools_and_catalog_produce_healthy_report(self) -> None:
        report = DoctorQuery(_ToolProbeStub(), _CatalogStub()).execute()
        self.assertTrue(report.healthy)
        self.assertEqual("ok", report.as_dict()["status"])

    def test_missing_tool_warns_without_failing_config_validation(self) -> None:
        report = DoctorQuery(_ToolProbeStub("pmtiles"), _CatalogStub()).execute()
        self.assertFalse(report.healthy)
        self.assertTrue(report.passed)
        self.assertEqual("warning", report.as_dict()["status"])
        missing = [tool for tool in report.tools if tool.health is ToolHealth.MISSING]
        self.assertEqual(["pmtiles"], [tool.name for tool in missing])

    def test_invalid_catalog_fails_report(self) -> None:
        report = DoctorQuery(_ToolProbeStub(), _InvalidCatalogStub()).execute()
        self.assertFalse(report.passed)
        self.assertEqual("failed", report.as_dict()["status"])

    def test_project_toolchain_takes_precedence_over_system_path(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            project_bin = root / ".devbox/nix/profile/default/bin"
            project_bin.mkdir(parents=True)
            tool = project_bin / "jq"
            tool.write_text("#!/bin/sh\nprintf 'jq-project-1.7.1\\n'\n", encoding="ascii")
            tool.chmod(0o755)
            status = ProcessToolProbe(root).probe(type("Requirement", (), {"name": "jq"})())
            self.assertEqual("jq-project-1.7.1", status.version)
            self.assertEqual(str(tool.absolute()), status.executable)
