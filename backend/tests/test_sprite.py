import hashlib
import tempfile
import subprocess
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.sprite import (
    SpriteRequest,
    hex_to_rgba,
    plan_sprite,
    render_sprite,
)
from huavd_map_build.production.north.local.sprite import SpriteService
from huavd_map_build.production.south.adapter.workspace.sprite import (
    FileSystemSpriteStore,
)
from huavd_map_build.shared.kernel import RegionId, SessionId


class SpritePlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = build_configuration_service(repository_root())
        cls.manifest = cls.configuration.sprite_manifest()

    def test_real_manifest_is_valid_and_has_unique_icons(self) -> None:
        ids = [icon["id"] for icon in self.manifest["icons"]]
        self.assertEqual(13, len(ids))
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual("service-area", self.manifest["icons"][5]["shape"])

    def test_one_x_plan_matches_existing_grid_contract(self) -> None:
        plan = plan_sprite(self.manifest, 1)
        self.assertEqual(192, plan.width)
        self.assertEqual(96, plan.height)
        self.assertEqual(
            {"width": 24, "height": 24, "x": 4, "y": 4, "pixelRatio": 1},
            plan.index()["peak"],
        )
        self.assertEqual(
            {"width": 24, "height": 24, "x": 4, "y": 68, "pixelRatio": 1},
            plan.index()["school"],
        )

    def test_two_x_plan_scales_pixels_and_preserves_logical_ratio(self) -> None:
        plan = plan_sprite(self.manifest, 2)
        self.assertEqual(384, plan.width)
        self.assertEqual(192, plan.height)
        self.assertEqual(
            {"width": 48, "height": 48, "x": 8, "y": 8, "pixelRatio": 2},
            plan.index()["peak"],
        )

    def test_color_parser_and_scale_validation(self) -> None:
        self.assertEqual((37, 99, 235, 255), hex_to_rgba("#2563eb"))
        with self.assertRaisesRegex(ValueError, "invalid color"):
            hex_to_rgba("#xyz")
        with self.assertRaisesRegex(ValueError, "unsupported sprite scale"):
            plan_sprite(self.manifest, 3)

    def test_renderer_is_byte_identical_to_current_shell(self) -> None:
        root = repository_root(Path(__file__))
        session = "china-guangxi-20261003"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                str(root / "scripts/sprite.sh"), "--region=china/guangxi",
                "--yyyymmdd=20261003", f"--session={session}",
                f"--workdir={directory}", "--force",
            ], cwd="/tmp", text=True, capture_output=True, timeout=30, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            output = Path(directory) / f"outputs/{session}.sprite"
            for scale, suffix in ((1, ""), (2, "@2x")):
                expected_json = (output / f"sprite{suffix}.json").read_bytes()
                expected_png = (output / f"sprite{suffix}.png").read_bytes()
                actual_json, actual_png = render_sprite(plan_sprite(self.manifest, scale))
                self.assertEqual(expected_json, actual_json)
                self.assertEqual(expected_png, actual_png)

    def test_service_publishes_complete_sprite_and_enforces_force(self) -> None:
        root = repository_root(Path(__file__))
        service = SpriteService(
            catalog_service(root), self.configuration, FileSystemSpriteStore()
        )
        session = SessionId("china-guangxi-20261003")
        with tempfile.TemporaryDirectory() as directory:
            request = SpriteRequest(
                RegionId("china/guangxi"), session, directory, False
            )
            paths = service.run(request)
            self.assertEqual(4, len(paths))
            for value in paths:
                artifact = Path(value)
                self.assertTrue(artifact.is_file())
                self.assertEqual(
                    f"{hashlib.sha512(artifact.read_bytes()).hexdigest()}  "
                    f"{artifact.name}\n",
                    Path(f"{artifact}.sha512").read_text(encoding="ascii"),
                )
            with self.assertRaisesRegex(ValueError, "pass --force"):
                service.run(request)
            marker = Path(paths[0]).parent / "obsolete"
            marker.write_text("old", encoding="ascii")
            service.run(SpriteRequest(request.region, session, directory, True))
            self.assertFalse(marker.exists())
