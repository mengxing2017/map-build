import subprocess
import unittest
from pathlib import Path


class MakefileBuildEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[2]

    def recipe(self, **variables: str) -> str:
        command = ["make", "--no-print-directory", "-n", "build"]
        command.extend(f"{key}={value}" for key, value in variables.items())
        return subprocess.run(
            command, cwd=self.root, text=True, capture_output=True, check=True
        ).stdout

    def test_base_without_glyph_uses_python_production_entrypoint(self) -> None:
        output = self.recipe(
            ROLE="base", GLYPH="0", REGION="china/guangxi",
            YYYYMMDD="20260803", WORKDIR="/tmp/maps",
            INPUT="/data/manual.osm.pbf", FORCE="1",
        )
        self.assertIn("build execute-vector", output)
        self.assertIn('--role="base"', output)
        self.assertIn('--input="/data/manual.osm.pbf"', output)
        self.assertIn("--force", output)
        self.assertNotIn("./scripts/build.sh", output)

    def test_base_glyph_and_combined_vector_roles_use_python(self) -> None:
        glyph = self.recipe(ROLE="base", GLYPH="1")
        combined = self.recipe(ROLE="both", GLYPH="0")
        self.assertIn("build execute-vector", glyph)
        self.assertIn('--glyph="1"', glyph)
        self.assertIn("build execute-vector", combined)
        self.assertIn('--role="both"', combined)
        self.assertNotIn("./scripts/build.sh", combined)

    def test_building_uses_python_with_explicit_catalog_override(self) -> None:
        output = self.recipe(
            ROLE="building", FORCE_BUILDING="1", INPUT="/data/manual.osm.pbf"
        )
        self.assertIn("build execute-vector", output)
        self.assertIn('--role="building"', output)
        self.assertIn("--force-building", output)
        self.assertNotIn("./scripts/build.sh", output)

    def test_raster_estimate_uses_python_planner(self) -> None:
        command = [
            "make", "--no-print-directory", "-n", "raster-estimate",
            "REGION=china/guangxi", "YYYYMMDD=20260803",
            "WORKDIR=/tmp/maps", "BAKE_MAX_TILES=500",
        ]
        output = subprocess.run(
            command, cwd=self.root, text=True, capture_output=True, check=True
        ).stdout
        self.assertIn("build raster-plan", output)
        self.assertIn('--max-tiles="500"', output)
        self.assertNotIn("render-bake.sh", output)

    def test_raster_roles_use_python_production_entrypoints(self) -> None:
        raster = self.recipe(ROLE="raster_bake")
        base_raster = self.recipe(
            ROLE="base_raster", INPUT="/data/manual.osm.pbf"
        )
        both_raster = self.recipe(
            ROLE="both_raster", INPUT="/data/manual.osm.pbf"
        )
        self.assertIn("build raster-bake", raster)
        self.assertNotIn("./scripts/build.sh", raster)
        self.assertIn("build execute-vector", base_raster)
        self.assertIn('--role="base"', base_raster)
        self.assertIn("build raster-bake", base_raster)
        self.assertIn('--input="/data/manual.osm.pbf"', base_raster)
        self.assertIn('--role="both"', both_raster)
        self.assertNotIn("./scripts/build.sh", both_raster)

    def test_vector_release_uses_python_pack_and_verification(self) -> None:
        command = [
            "make", "--no-print-directory", "-n", "release",
            "ROLE=both", "REGION=china/guangxi", "YYYYMMDD=20260818",
            "WORKDIR_ROOT=/tmp/maps", "INPUT=/data/manual.osm.pbf",
        ]
        output = subprocess.run(
            command, cwd=self.root, text=True, capture_output=True, check=True
        ).stdout
        self.assertIn("artifact pack", output)
        self.assertIn("quality release", output)
        self.assertNotIn("scripts/pack.sh", output)
        self.assertNotIn("scripts/verify.sh", output)
