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
            "710d0e7880470eae7792ee643b3cd6c0b966788bc03ec735f6bf3b802a8cdb0dd2"
            "89e97bcf6b2d60721233629c65d0cb3c3c43ee10e08f253cc299aa09afb94e",
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
        # Guilin and Qixing are explicitly configured local-extract regions.
        self.assertEqual(4058, len(snapshot["regions"]))
        self.assertTrue(any(item["id"] == "china/guangxi/guilin/qixing" for item in snapshot["regions"]))
        self.assertEqual("广西壮族自治区", guangxi["display_name_zh"])
        self.assertEqual("cn-45-base", guangxi["region_id"])
