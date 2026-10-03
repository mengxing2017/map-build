import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root, workspace_initializer
from huavd_map_build.production.domain.workspace import WorkspacePlan
from huavd_map_build.shared.kernel import SessionId


class WorkspaceInitializerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def test_initializes_directory_contract_and_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory) / "workspace"
            result = workspace_initializer(self.root).initialize(
                WorkspacePlan(
                    str(workdir),
                    SessionId("china-guangxi-20260818"),
                    directory_mode=0o710,
                )
            )
            expected = (
                "bin",
                "tools",
                "mirror",
                "cache/bake",
                "cache/tags-filter",
                "staging/china-guangxi-20260818/layers",
                "outputs",
                "config/regions",
                "config/export-config",
            )
            self.assertTrue(all((workdir / path).is_dir() for path in expected))
            self.assertEqual(0o755, stat.S_IMODE(workdir.stat().st_mode))
            self.assertEqual(0o710, stat.S_IMODE((workdir / "outputs").stat().st_mode))
            self.assertEqual("initialized", result.as_dict()["status"])

    def test_copy_config_preserves_content_and_applies_modes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory) / "workspace"
            workspace_initializer(self.root).initialize(
                WorkspacePlan(
                    str(workdir),
                    SessionId("china-guangxi-20260818"),
                    copy_config=True,
                    config_directory_mode=0o750,
                    config_file_mode=0o640,
                )
            )
            copied = workdir / "config/regions.yaml"
            self.assertEqual(
                (self.root / "config/regions.yaml").read_bytes(), copied.read_bytes()
            )
            self.assertEqual(0o750, stat.S_IMODE(copied.parent.stat().st_mode))
            self.assertEqual(0o640, stat.S_IMODE(copied.stat().st_mode))

    def test_shell_entrypoint_keeps_environment_and_invalid_session_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(
                HUAVD_MAP_BUILD_HOME=directory,
                HUAVD_MAP_BUILD_SESSION="invalid/session",
            )
            result = subprocess.run(
                [str(self.root / "scripts/init-workdir.sh")],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
        self.assertEqual(64, result.returncode)
        self.assertIn("invalid HUAVD_MAP_BUILD_SESSION", result.stderr)

    def test_shell_entrypoint_initializes_from_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ.copy()
            environment.update(
                HUAVD_MAP_BUILD_HOME=directory,
                HUAVD_MAP_BUILD_SESSION="china-guangxi-20260818",
            )
            result = subprocess.run(
                [str(self.root / "scripts/init-workdir.sh")],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )
            initialized = Path(directory) / "staging/china-guangxi-20260818/layers"
            self.assertTrue(initialized.is_dir())
        self.assertEqual(0, result.returncode, result.stderr)
