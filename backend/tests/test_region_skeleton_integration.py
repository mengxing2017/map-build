import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from huavd_map_build.bootstrap import region_skeleton_service, repository_root


class RegionSkeletonIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.fixtures = cls.root / "backend/tests/fixtures"

    def test_fixture_matches_frozen_ruby_generator_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "regions.yaml"
            region_skeleton_service().write(
                str(self.fixtures / "iso3166-sample.csv"),
                str(self.fixtures / "skeleton-existing.yaml"),
                str(output),
            )
            document = yaml.safe_load(output.read_text(encoding="utf-8"))
        canonical = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        self.assertEqual(
            "46faa27c14d133a368d15b0bfd52ab12c3ae53f6889a67c952654bec80ca8420"
            "e1d6277ef0297048663e8786534811f199565a6a055d75da2be13daa57bee8d6",
            hashlib.sha512(canonical).hexdigest(),
        )

    def test_stdout_mode_excludes_existing_regions(self) -> None:
        rendered = region_skeleton_service().render_new(
            str(self.fixtures / "iso3166-sample.csv"),
            str(self.fixtures / "skeleton-existing.yaml"),
        )
        skeletons = yaml.safe_load(rendered)
        identities = [item["id"] for item in skeletons]
        self.assertNotIn("china/guangdong", identities)
        self.assertIn("china/guangdong/alpha-district", identities)

    def test_shell_entrypoint_runs_outside_repository(self) -> None:
        result = subprocess.run(
            [
                str(self.root / "scripts/generate-region-skeletons.sh"),
                f"--iso3166-2-csv={self.fixtures / 'iso3166-sample.csv'}",
                f"--existing-config={self.fixtures / 'skeleton-existing.yaml'}",
            ],
            cwd="/tmp",
            env=os.environ.copy(),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
        skeletons = yaml.safe_load(result.stdout)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("china/guangdong/alpha-district", [item["id"] for item in skeletons])
