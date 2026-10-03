import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from huavd_map_build.delivery.domain.metadata import PmtilesHeader
from huavd_map_build.production.domain.raster import (
    RasterBounds,
    RasterCacheIdentity,
    RasterTileCoordinate,
    create_raster_tile_plan,
    webp_dimensions,
)
from huavd_map_build.production.north.local.raster import (
    RasterPlanningService,
    RasterPlanRequest,
)
from huavd_map_build.production.south.adapter.workspace.raster import (
    FileSystemRasterCacheStore,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class RasterTilePlanTest(unittest.TestCase):
    def test_matches_shell_bbox_rectangle_plan(self) -> None:
        plan = create_raster_tile_plan(
            RasterBounds(108.28, 22.77, 108.39, 22.89), 10, 12, 1
        )
        self.assertEqual([10, 11, 12], [item.zoom for item in plan.ranges])
        self.assertEqual(
            plan.tile_count,
            sum(item["tile_count"] for item in plan.as_dict()["tiles_by_zoom"]),
        )
        self.assertEqual("bbox-rectangle-with-padding", plan.as_dict()["coverage_strategy"])

    def test_rejects_invalid_bounds_zoom_and_limit(self) -> None:
        with self.assertRaisesRegex(ValueError, "west < east"):
            RasterBounds(10, 0, 10, 1)
        with self.assertRaisesRegex(ValueError, "min_zoom"):
            create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 5, 4, 0)
        with self.assertRaisesRegex(ValueError, "exceeds max_tiles"):
            create_raster_tile_plan(RasterBounds(-10, -10, 10, 10), 5, 8, 1, 1)

    def test_coordinate_tsv_contains_center_and_exact_bounds(self) -> None:
        coordinate = RasterTileCoordinate(1, 1, 0)
        fields = coordinate.tsv().rstrip().split("\t")
        self.assertEqual(["1", "1", "0"], fields[:3])
        self.assertEqual("90.00000000", fields[3])
        self.assertEqual("0.000000000000,0.000000000000,180.000000000000,85.051128779807", fields[5])

    def test_reads_lossless_webp_dimensions(self) -> None:
        bits = (255 | (255 << 14)).to_bytes(4, "little")
        chunk = b"\x2f" + bits
        payload = b"RIFF" + (len(chunk) + 12).to_bytes(4, "little") + b"WEBPVP8L"
        payload += len(chunk).to_bytes(4, "little") + chunk + b"\x00"
        self.assertEqual((256, 256), webp_dimensions(payload))

    def test_cache_identity_is_stable_and_parameter_sensitive(self) -> None:
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 2, 3, 0)
        arguments = dict(
            base_sha512="a" * 128, style_sha512="b" * 128,
            configuration_sha512="c" * 128, plan=plan, tile_size=256,
            pixel_ratio=1, webp_lossless=True, webp_method=6,
            webp_metadata="none", renderer_engine="mbgl-renderer",
            renderer_identity="mbgl-render 1.0",
        )
        first = RasterCacheIdentity(**arguments)
        self.assertEqual(first.digest, RasterCacheIdentity(**arguments).digest)
        changed = RasterCacheIdentity(**{**arguments, "webp_method": 5})
        self.assertNotEqual(first.digest, changed.digest)
        changed_renderer = RasterCacheIdentity(
            **{**arguments, "renderer_identity": "mbgl-render 2.0"}
        )
        self.assertNotEqual(first.digest, changed_renderer.digest)


class ConfigurationStub:
    def raster_bake(self, region: str):
        return {"min_zoom": 2, "max_zoom": 3, "bbox_padding_tiles": 0,
                "max_tiles": None}


class HeaderStub:
    def read(self, path: str):
        self.path = path
        return PmtilesHeader(
            tile_type=1, tile_compression=2, min_zoom=0, max_zoom=14,
            bounds=(108.0, 22.0, 109.0, 23.0), internal_compression=2,
            root_offset=127, root_length=10,
        )


class RasterPlanningServiceTest(unittest.TestCase):
    def test_uses_managed_base_header_and_effective_configuration(self) -> None:
        headers = HeaderStub()
        plan = RasterPlanningService(ConfigurationStub(), headers).plan(
            RasterPlanRequest(
                RegionId("china/guangxi"), BuildDate("20260803"), "/tmp/maps"
            )
        )
        self.assertEqual(2, plan.min_zoom)
        self.assertEqual(3, plan.max_zoom)
        self.assertEqual(
            "/tmp/maps/outputs/china-guangxi-20260803.base.pmtiles", headers.path
        )


class RasterCacheStoreTest(unittest.TestCase):
    @staticmethod
    def webp(size: int = 256) -> bytes:
        bits = ((size - 1) | ((size - 1) << 14)).to_bytes(4, "little")
        chunk = b"\x2f" + bits
        return (
            b"RIFF" + (len(chunk) + 12).to_bytes(4, "little") + b"WEBPVP8L"
            + len(chunk).to_bytes(4, "little") + chunk + b"\x00"
        )

    def test_writes_plan_and_streaming_tile_list(self) -> None:
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 2, 2, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            FileSystemRasterCacheStore().write_plan(
                plan, str(root / "plan.json"), str(root / "tiles.tsv")
            )
            document = json.loads((root / "plan.json").read_text())
            lines = (root / "tiles.tsv").read_text().splitlines()
        self.assertEqual(plan.tile_count, document["tile_count"])
        self.assertEqual(plan.tile_count, len(lines))

    def test_scans_hot_missing_unverified_and_invalid_tiles(self) -> None:
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 2, 2, 0)
        coordinates = list(plan.coordinates())
        self.assertGreaterEqual(len(coordinates), 2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            webp = root / "webp"
            first, second = coordinates[:2]
            hot = webp / str(first.zoom) / str(first.x) / f"{first.y}.webp"
            hot.parent.mkdir(parents=True)
            payload = self.webp()
            hot.write_bytes(payload)
            Path(f"{hot}.sha512").write_text(
                f"{hashlib.sha512(payload).hexdigest()}  {hot.name}\n"
            )
            invalid = webp / str(second.zoom) / str(second.x) / f"{second.y}.webp"
            invalid.parent.mkdir(parents=True, exist_ok=True)
            invalid.write_bytes(b"not-webp")
            result = FileSystemRasterCacheStore().scan(
                plan, str(webp), str(root / "missing.tsv"),
                str(root / "quarantine"), 256,
            )
            missing_lines = (root / "missing.tsv").read_text().splitlines()
            quarantined = list((root / "quarantine").rglob("*.invalid"))
        self.assertEqual(1, result.cache_hits)
        self.assertEqual(1, result.structurally_invalid_tiles)
        self.assertEqual(plan.tile_count - 1, result.missing_tiles)
        self.assertEqual(result.missing_tiles, len(missing_lines))
        self.assertEqual(1, len(quarantined))
