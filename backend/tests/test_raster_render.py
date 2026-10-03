from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.raster import (
    MissingRasterToolError,
    RasterBatchExecutionError,
    RasterRenderSettings,
    RasterTileCoordinate,
)
from huavd_map_build.production.north.local.raster_render import RasterRenderService
from huavd_map_build.production.south.adapter.process.raster import (
    ProcessRasterTileRenderer,
    ProcessWebpEncoder,
)
from huavd_map_build.production.south.adapter.workspace.raster_queue import (
    FileSystemRasterWorkQueue,
)


def lossless_webp(size: int = 256) -> bytes:
    bits = ((size - 1) | ((size - 1) << 14)).to_bytes(4, "little")
    chunk = b"\x2f" + bits
    return (
        b"RIFF" + (len(chunk) + 12).to_bytes(4, "little") + b"WEBPVP8L"
        + len(chunk).to_bytes(4, "little") + chunk + b"\x00"
    )


class RasterProcessAdapterTest(unittest.TestCase):
    def settings(self, root: Path, **overrides) -> RasterRenderSettings:
        values = dict(
            style_path=str(root / "style.json"), png_directory=str(root / "png"),
            webp_directory=str(root / "webp"),
        )
        values.update(overrides)
        return RasterRenderSettings(**values)

    def test_mbgl_renderer_uses_argument_vector_and_exact_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            output = root / "tile.png"

            def run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                output.write_bytes(b"png")
                return subprocess.CompletedProcess(arguments, 0)

            with patch("shutil.which", return_value="/tools/mbgl-render"), patch(
                "subprocess.run", side_effect=run
            ):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(1, 1, 0), self.settings(root), str(output)
                )
        self.assertEqual("/tools/mbgl-render", calls[0][0][0])
        self.assertEqual(["256", "256", "-b"], calls[0][0][3:6])
        self.assertNotIn("shell", calls[0][1])
        self.assertEqual(120, calls[0][1]["timeout"])

    def test_maplibre_renderer_uses_named_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            output = root / "tile.png"

            def run(arguments, **kwargs):
                calls.append(arguments)
                output.write_bytes(b"png")
                return subprocess.CompletedProcess(arguments, 0)

            settings = self.settings(
                root, renderer_engine="maplibre-native", renderer_command="renderer"
            )
            with patch("shutil.which", return_value="/tools/renderer"), patch(
                "subprocess.run", side_effect=run
            ):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(1, 1, 0), settings, str(output)
                )
        self.assertEqual("--style", calls[0][1])
        self.assertEqual("--output", calls[0][-2])

    def test_encoder_validates_and_publishes_webp_and_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root, calls = Path(temporary), []
            source, target = root / "tile.png", root / "out" / "tile.webp"
            source.write_bytes(b"png")

            def run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                if arguments[0] == "/tools/cwebp":
                    Path(arguments[-1]).write_bytes(lossless_webp())
                return subprocess.CompletedProcess(arguments, 0)

            with patch(
                "shutil.which", side_effect=lambda command: f"/tools/{command}"
            ), patch("subprocess.run", side_effect=run):
                ProcessWebpEncoder().encode(
                    str(source), str(target), self.settings(root)
                )
            self.assertEqual(lossless_webp(), target.read_bytes())
            self.assertTrue(Path(f"{target}.sha512").is_file())
            self.assertEqual(["-lossless", "-m", "6", "-metadata", "none"], calls[0][0][1:6])
            self.assertEqual("/tools/dwebp", calls[1][0][0])
            self.assertNotIn("shell", calls[0][1])

    def test_missing_tool_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary, patch(
            "shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(MissingRasterToolError, "mbgl-render"):
                ProcessRasterTileRenderer().render(
                    RasterTileCoordinate(0, 0, 0),
                    self.settings(Path(temporary)), str(Path(temporary) / "tile.png"),
                )


class TrackingRenderer:
    def __init__(self, fail_once: RasterTileCoordinate | None = None) -> None:
        self.fail_once = fail_once
        self.calls: dict[RasterTileCoordinate, int] = {}
        self.active = 0
        self.maximum_active = 0
        self.lock = threading.Lock()

    def render(self, coordinate, settings, output_path) -> None:
        with self.lock:
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
            self.calls[coordinate] = self.calls.get(coordinate, 0) + 1
            call = self.calls[coordinate]
        try:
            time.sleep(0.01)
            if coordinate == self.fail_once and call == 1:
                raise RuntimeError("transient")
            Path(output_path).write_bytes(b"png")
        finally:
            with self.lock:
                self.active -= 1


class FakeEncoder:
    def encode(self, input_path, output_path, settings) -> None:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(lossless_webp(settings.tile_size))


class RasterRenderServiceTest(unittest.TestCase):
    def test_streams_with_bounded_workers_and_retries_only_failure(self) -> None:
        coordinates = [RasterTileCoordinate(3, index, 0) for index in range(6)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            renderer = TrackingRenderer(coordinates[2])
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                parallel_jobs=2, retries=1,
            )
            result = RasterRenderService(
                FileSystemRasterWorkQueue(), renderer, FakeEncoder()
            ).render(str(queue), settings)
        self.assertEqual(6, result.planned_tiles)
        self.assertEqual(7, result.attempts)
        self.assertEqual(1, result.retried_tiles)
        self.assertLessEqual(renderer.maximum_active, 2)
        self.assertEqual(2, renderer.calls[coordinates[2]])
        self.assertTrue(all(
            count == 1 for coordinate, count in renderer.calls.items()
            if coordinate != coordinates[2]
        ))

    def test_reports_failed_batch_after_retry_budget(self) -> None:
        coordinate = RasterTileCoordinate(0, 0, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "tiles.tsv"
            queue.write_text(coordinate.tsv(), encoding="utf-8")
            renderer = TrackingRenderer(coordinate)
            settings = RasterRenderSettings(
                str(root / "style.json"), str(root / "png"), str(root / "webp"),
                retries=0,
            )
            with self.assertRaises(RasterBatchExecutionError) as raised:
                RasterRenderService(
                    FileSystemRasterWorkQueue(), renderer, FakeEncoder()
                ).render(str(queue), settings)
        self.assertEqual(1, raised.exception.failed_tiles)
        self.assertEqual(1, len(raised.exception.samples))

    def test_queue_rejects_invalid_rows_with_line_number(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            queue = Path(temporary) / "tiles.tsv"
            queue.write_text("zoom\tx\ty\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "row 1"):
                list(FileSystemRasterWorkQueue().coordinates(str(queue)))


if __name__ == "__main__":
    unittest.main()
