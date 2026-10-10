import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import repository_root


class CatalogSnapshotTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))

    def test_shell_entrypoint_matches_frozen_snapshot_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.json"
            environment = os.environ.copy()
            environment["OUTPUT"] = str(output)
            result = subprocess.run(
                [str(self.root / "scripts/manifest-catalog.sh")],
                cwd="/tmp",
                env=environment,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
            actual = json.loads(output.read_text(encoding="utf-8"))
        canonical = json.dumps(
            actual, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(
            "689015ae02d17a21693d7528bca7b424497bf3bcdc813dde780d9354f342bcb1a"
            "539aa892f5a7ec75ad4bf2e5d0446e3ffa33fef838a09ffc3499fbf3728388e",
            hashlib.sha512(canonical).hexdigest(),
        )

    def test_snapshot_contains_expected_region_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "catalog.json"
            result = subprocess.run(
                [
                    str(self.root / "scripts/manifest-catalog.sh"),
                ],
                cwd="/tmp",
                env={**os.environ, "OUTPUT": str(output)},
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
            snapshot = json.loads(output.read_text(encoding="utf-8"))
        guangxi = next(item for item in snapshot["regions"] if item["id"] == "china/guangxi")
        self.assertEqual(4056, len(snapshot["regions"]))
        self.assertNotIn("china/guangxi/guilin/qixing", {item["id"] for item in snapshot["regions"]})
        self.assertEqual("广西壮族自治区", guangxi["display_name_zh"])
        self.assertEqual("cn-45-base", guangxi["region_id"])
