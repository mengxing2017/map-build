import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class StyleEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entrypoint = repository_root(Path(__file__)) / "scripts/style.sh"

    def test_help_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--pmtiles-url=<url>", result.stdout)

    def test_unknown_argument_keeps_input_exit_code(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--unknown"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, result.returncode)
