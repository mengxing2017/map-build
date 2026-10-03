import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class YamlJsonBridgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def test_shell_config_bridge_writes_equivalent_json_and_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workdir = Path(directory) / "work"
            command = (
                "source scripts/lib/common.sh; source scripts/lib/config.sh; "
                "config_json_path layers"
            )
            environment = {**os.environ, "WORKDIR": str(workdir)}
            first = subprocess.run(
                ["bash", "-c", command], cwd=self.root, env=environment,
                text=True, capture_output=True, timeout=30, check=False,
            )
            output = Path(first.stdout.strip())
            first_mtime = output.stat().st_mtime_ns
            time.sleep(0.01)
            second = subprocess.run(
                ["bash", "-c", command], cwd=self.root, env=environment,
                text=True, capture_output=True, timeout=30, check=False,
            )
            second_mtime = output.stat().st_mtime_ns
            document = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual(1, document["schema_version"])
        self.assertEqual(first_mtime, second_mtime)

    def test_invalid_yaml_does_not_publish_partial_target(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.yaml"
            target = Path(directory) / "output.json"
            source.write_text("value: [unterminated\n", encoding="utf-8")
            result = subprocess.run(
                [
                    str(self.root / ".venv/bin/python"), "-m", "huavd_map_build",
                    "catalog", "yaml-to-json", f"--source={source}", f"--output={target}",
                ],
                cwd=self.root,
                env={**os.environ, "PYTHONPATH": "backend/src"},
                text=True, capture_output=True, timeout=30, check=False,
            )
            target_exists = target.exists()
            temporary = list(Path(directory).glob(".output.json.*.tmp"))
        self.assertEqual(2, result.returncode)
        self.assertFalse(target_exists)
        self.assertEqual([], temporary)
