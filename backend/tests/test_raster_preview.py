from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.raster import RasterBounds, create_raster_tile_plan
from huavd_map_build.production.south.adapter.process.raster_preview import write_preview


class RasterPreviewTest(unittest.TestCase):
    def test_preview_uses_adjacent_xyz_and_does_not_claim_visual_acceptance(self):
        plan = create_raster_tile_plan(RasterBounds(110, 25, 111, 26), 12, 14, 1)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "huavd_map_build.production.south.adapter.process.raster_preview.subprocess.run"
        ) as run:
            result = write_preview(Path(temporary), plan)
            page = Path(result["preview"]).read_text()
            self.assertEqual(20, run.call_count)
            self.assertIn("padding", page)
            self.assertIn("XYZ z14", page)
            self.assertEqual("not-run", result["visual_acceptance"])
            first, neighbor = run.call_args_list[:2]
            left, right = Path(first.args[0][1]), Path(neighbor.args[0][1])
            self.assertEqual(int(left.parent.name) + 1, int(right.parent.name))
            self.assertEqual(left.name, right.name)

    def test_decode_failure_is_not_presented_as_success(self):
        plan = create_raster_tile_plan(RasterBounds(0, 0, 1, 1), 0, 0, 0)
        with tempfile.TemporaryDirectory() as temporary, patch(
            "huavd_map_build.production.south.adapter.process.raster_preview.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "dwebp"),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                write_preview(Path(temporary), plan)
            self.assertFalse((Path(temporary) / "acceptance/index.html").exists())
