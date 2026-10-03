import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class TippecanoeEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entrypoint = repository_root(Path(__file__)) / "scripts/tippecanoe.sh"

    def test_help_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("base|building", result.stdout)

    def test_invalid_role_keeps_input_error_exit_code(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--role=both"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("base or building", result.stderr)
