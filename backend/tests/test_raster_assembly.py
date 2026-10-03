from __future__ import annotations

import hashlib
from pathlib import Path
import sqlite3
import subprocess
import shutil
import tempfile
import unittest
from unittest.mock import patch

from huavd_map_build.production.domain.raster import (
    RasterAssemblySettings,
    RasterBounds,
    RasterExecutionError,
    RasterTileCoordinate,
)
from huavd_map_build.production.north.local.raster_assembly import (
    RasterAssemblyRequest,
    RasterAssemblyService,
)
from huavd_map_build.production.south.adapter.process.raster_archive import (
    ProcessRasterArchive,
)
from huavd_map_build.production.south.adapter.workspace.raster_mbtiles import (
    SqliteRasterTileArchiveAssembler,
)


def lossless_webp(size: int = 256) -> bytes:
    bits = ((size - 1) | ((size - 1) << 14)).to_bytes(4, "little")
    chunk = b"\x2f" + bits
    return (
        b"RIFF" + (len(chunk) + 12).to_bytes(4, "little") + b"WEBPVP8L"
        + len(chunk).to_bytes(4, "little") + chunk + b"\x00"
    )


class RasterMbtilesAssemblerTest(unittest.TestCase):
    @staticmethod
    def settings(root: Path) -> RasterAssemblySettings:
        return RasterAssemblySettings(
            "test-raster", RasterBounds(0, 0, 1, 1), 1, 2, str(root / "webp")
        )

    @staticmethod
    def write_tile(root: Path, coordinate: RasterTileCoordinate) -> None:
        tile = root / "webp" / str(coordinate.zoom) / str(coordinate.x) / f"{coordinate.y}.webp"
        tile.parent.mkdir(parents=True, exist_ok=True)
        payload = lossless_webp()
        tile.write_bytes(payload)
        Path(f"{tile}.sha512").write_text(
            f"{hashlib.sha512(payload).hexdigest()}  {tile.name}\n", encoding="utf-8"
        )

    def test_assembles_only_queue_tiles_with_tms_rows_and_metadata(self) -> None:
        coordinates = [RasterTileCoordinate(1, 1, 0), RasterTileCoordinate(2, 2, 3)]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for coordinate in coordinates:
                self.write_tile(root, coordinate)
            queue, output = root / "tiles.tsv", root / "raster.mbtiles"
            queue.write_text("".join(item.tsv() for item in coordinates), encoding="utf-8")
            result = SqliteRasterTileArchiveAssembler().assemble(
                str(queue), str(output), self.settings(root)
            )
            with sqlite3.connect(output) as connection:
                rows = connection.execute(
                    "select zoom_level, tile_column, tile_row from tiles order by zoom_level"
                ).fetchall()
                metadata = dict(connection.execute("select name, value from metadata"))
        self.assertEqual([(1, 1, 1), (2, 2, 0)], rows)
        self.assertEqual("webp", metadata["format"])
        self.assertEqual("2", metadata["tile_count"])
        self.assertEqual(2, result.inserted_tiles)
        self.assertEqual(2 * len(lossless_webp()), result.tile_bytes)

    def test_invalid_cache_does_not_replace_existing_archive(self) -> None:
        coordinate = RasterTileCoordinate(1, 1, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue, output = root / "tiles.tsv", root / "raster.mbtiles"
            queue.write_text(coordinate.tsv(), encoding="utf-8")
            output.write_bytes(b"previous")
            with self.assertRaisesRegex(RasterExecutionError, "invalid raster cache"):
                SqliteRasterTileArchiveAssembler().assemble(
                    str(queue), str(output), self.settings(root)
                )
            self.assertEqual(b"previous", output.read_bytes())

    def test_duplicate_coordinate_is_rejected_by_unique_index(self) -> None:
        coordinate = RasterTileCoordinate(1, 1, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_tile(root, coordinate)
            queue = root / "tiles.tsv"
            queue.write_text(coordinate.tsv() * 2, encoding="utf-8")
            with self.assertRaisesRegex(RasterExecutionError, "UNIQUE constraint"):
                SqliteRasterTileArchiveAssembler().assemble(
                    str(queue), str(root / "out.mbtiles"), self.settings(root)
                )


class RasterArchiveProcessTest(unittest.TestCase):
    def test_extract_and_convert_use_argument_vectors_and_atomic_outputs(self) -> None:
        calls = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)

            def run(arguments, **kwargs):
                calls.append((arguments, kwargs))
                output_index = 3 if arguments[1] == "extract" else 3
                Path(arguments[output_index]).write_bytes(b"pmtiles")
                return subprocess.CompletedProcess(arguments, 0)

            archive = ProcessRasterArchive()
            with patch("shutil.which", return_value="/tools/pmtiles"), patch(
                "subprocess.run", side_effect=run
            ):
                archive.extract(
                    str(root / "base.pmtiles"), str(root / "subset.pmtiles"),
                    "1,2,3,4", 2, 8,
                )
                archive.convert(str(root / "raster.mbtiles"), str(root / "raster.pmtiles"))
            self.assertEqual(
                ["--bbox=1,2,3,4", "--minzoom=2", "--maxzoom=8"], calls[0][0][4:]
            )
            self.assertEqual("convert", calls[1][0][1])
            self.assertNotIn("shell", calls[0][1])
            self.assertIsNone(calls[0][1]["timeout"])
            self.assertEqual(b"pmtiles", (root / "subset.pmtiles").read_bytes())
            self.assertEqual(b"pmtiles", (root / "raster.pmtiles").read_bytes())

    def test_failed_convert_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "raster.pmtiles"
            output.write_bytes(b"previous")
            with patch("shutil.which", return_value="/tools/pmtiles"), patch(
                "subprocess.run",
                return_value=subprocess.CompletedProcess([], 1),
            ):
                with self.assertRaisesRegex(RasterExecutionError, "exit code 1"):
                    ProcessRasterArchive().convert(str(root / "in.mbtiles"), str(output))
            self.assertEqual(b"previous", output.read_bytes())

    @unittest.skipUnless(shutil.which("pmtiles"), "pmtiles is not installed")
    def test_real_pmtiles_converts_assembled_webp_archive(self) -> None:
        coordinate = RasterTileCoordinate(0, 0, 0)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            RasterMbtilesAssemblerTest.write_tile(root, coordinate)
            queue = root / "tiles.tsv"
            queue.write_text(coordinate.tsv(), encoding="utf-8")
            settings = RasterAssemblySettings(
                "test-raster", RasterBounds(-180, -85, 180, 85), 0, 0,
                str(root / "webp"),
            )
            mbtiles, pmtiles = root / "raster.mbtiles", root / "raster.pmtiles"
            SqliteRasterTileArchiveAssembler().assemble(
                str(queue), str(mbtiles), settings
            )
            ProcessRasterArchive().convert(str(mbtiles), str(pmtiles))
            header = pmtiles.read_bytes()[:7]
        self.assertEqual(b"PMTiles", header)


class FakeAssembler:
    def assemble(self, queue_path, output_path, settings):
        Path(output_path).write_bytes(b"mbtiles")
        from huavd_map_build.production.domain.raster import RasterAssemblyResult
        return RasterAssemblyResult(1, 1, 10)


class FakeConverter:
    def __init__(self) -> None:
        self.calls = []

    def convert(self, input_path, output_path):
        self.calls.append((input_path, output_path))


class RasterAssemblyServiceTest(unittest.TestCase):
    def test_converts_only_after_successful_assembly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            converter = FakeConverter()
            settings = RasterAssemblySettings(
                "test", RasterBounds(0, 0, 1, 1), 0, 0, str(root / "webp")
            )
            request = RasterAssemblyRequest(
                str(root / "queue"), str(root / "out.mbtiles"),
                str(root / "out.pmtiles"), settings,
            )
            result = RasterAssemblyService(FakeAssembler(), converter).assemble(request)
        self.assertEqual(1, result.inserted_tiles)
        self.assertEqual([(request.mbtiles_path, request.pmtiles_path)], converter.calls)


if __name__ == "__main__":
    unittest.main()
