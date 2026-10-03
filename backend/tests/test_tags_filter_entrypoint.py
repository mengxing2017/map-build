import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class TagsFilterEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.entrypoint = repository_root(Path(__file__)) / "scripts/tags-filter.sh"

    def test_help_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--help"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("--layers=all|layer[,layer...]", result.stdout)

    def test_unknown_argument_keeps_input_error_exit_code(self) -> None:
        result = subprocess.run(
            [str(self.entrypoint), "--unknown"], cwd="/tmp", text=True,
            capture_output=True, timeout=30, check=False,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("unknown argument", result.stderr)
