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

    def test_engine_defaults_are_resolved_by_catalog_and_overrides_are_forwarded(self) -> None:
        output = self.recipe(ROLE="raster_bake", BAKE_RENDERER_ENGINE="maplibre-native-headless", BAKE_JOBS="2")
        self.assertIn('--renderer-engine="maplibre-native-headless"', output)
        self.assertNotIn('--renderer-command=', output)
        self.assertIn('--jobs="2"', output)
        samples = self.recipe(ROLE="raster_bake", BAKE_SAMPLES="road,110.3,25.3 water,110.31,25.31")
        self.assertIn('--sample="road,110.3,25.3"', samples)
        self.assertIn('--sample="water,110.31,25.31"', samples)
        default = subprocess.run(["make","--no-print-directory","-n"], cwd=self.root, text=True, capture_output=True, check=True).stdout
        self.assertNotIn("setup-native-renderer", default)
        self.assertNotIn('--renderer-engine=', self.recipe(ROLE="raster_bake"))
        legacy = self.recipe(ROLE="raster_bake", BAKE_RENDERER_ENGINE="mbgl-renderer", BAKE_RENDERER_COMMAND="legacy-render")
        self.assertIn('--renderer-command="legacy-render"', legacy)

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

    def test_mixed_verify_runs_python_deep_release_before_legacy_raster_checks(self):
        for role, vector_role in (("base_raster", "base"), ("both_raster", "both"), ("all", "both")):
            with self.subTest(role=role):
                result = subprocess.run(["make", "--no-print-directory", "-n", "verify", f"ROLE={role}",
                                         "REGION=china/sichuan", "YYYYMMDD=20261026"],
                                        cwd=self.root, capture_output=True, text=True, check=True)
                self.assertIn(f'--role="{vector_role}"', result.stdout)
                self.assertLess(result.stdout.index("quality release"), result.stdout.index("scripts/verify.sh"))

    def test_raster_release_checks_environment_and_inherits_output_directory(self) -> None:
        for directory, expected in (
            ("WORKDIR_ROOT=/tmp/maps", "/tmp/maps/china-guangxi-20260818"),
            ("RELEASE_WORKDIR=/tmp/custom-map", "/tmp/custom-map"),
        ):
            with self.subTest(directory=directory):
                output = subprocess.run([
                    "make", "--no-print-directory", "-n", "release",
                    "ROLE=base_raster", "FORMAT=zip", "REGION=china/guangxi",
                    "YYYYMMDD=20260818", "INPUT=/data/manual.osm.pbf", directory,
                ], cwd=self.root, text=True, capture_output=True, check=True).stdout
                self.assertLess(output.index("huavd_map_build doctor"),
                                output.index("build execute-vector"))
                for line in output.splitlines():
                    if "--workdir=" in line:
                        self.assertIn(f'--workdir="{expected}"', line)
