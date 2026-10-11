"""Read every planned XYZ from the candidate and compare it with the checked cache."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import tempfile

from huavd_map_build.production.domain.raster import RasterExecutionError, RasterTileCoordinate, webp_dimensions
from huavd_map_build.production.south.adapter.process.raster import _environment, _executable, _run


class ProcessRasterArchiveVerifier:
    def verify(self, archive: str, queue: str, webp_directory: str, tile_size: int) -> int:
        pmtiles, dwebp = _executable("pmtiles"), _executable("dwebp")
        report = Path(archive).with_suffix(".readback.json")
        report.unlink(missing_ok=True)
        decoded: set[str] = set()
        count = 0
        with Path(queue).open(encoding="utf-8") as rows:
            total = sum(1 for _ in rows)
        started = last_progress = time.monotonic()
        print(f"raster readback started tiles={total} archive={archive}", file=sys.stderr, flush=True)
        with tempfile.TemporaryDirectory(prefix="huavd-raster-readback-") as directory:
            image = Path(directory) / "tile.webp"
            with Path(queue).open(encoding="utf-8") as rows:
                for row in rows:
                    coordinate = RasterTileCoordinate.from_tsv(row)
                    label = f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}"
                    result = subprocess.run(
                        [pmtiles, "tile", archive, str(coordinate.zoom), str(coordinate.x), str(coordinate.y)],
                        env=_environment(), capture_output=True, timeout=30, check=False,
                    )
                    if result.returncode != 0:
                        raise RasterExecutionError(f"raster readback failed: {label}")
                    payload = result.stdout
                    if webp_dimensions(payload) != (tile_size, tile_size):
                        raise RasterExecutionError(f"raster readback dimensions differ: {label}")
                    cached = Path(webp_directory) / str(coordinate.zoom) / str(coordinate.x) / f"{coordinate.y}.webp"
                    if payload != cached.read_bytes():
                        raise RasterExecutionError(f"raster readback differs from cache: {label}")
                    digest = hashlib.sha512(payload).hexdigest()
                    if digest not in decoded:
                        image.write_bytes(payload)
                        _run([dwebp, str(image), "-quiet", "-o", os.devnull], 30, "raster readback decode")
                        decoded.add(digest)
                    count += 1
                    now = time.monotonic()
                    if now - last_progress >= 10 or count == total:
                        elapsed = max(now - started, 0.001)
                        rate = count / elapsed
                        remaining = (total - count) / rate
                        print(
                            f"raster readback {count}/{total} ({count / total:.1%}) "
                            f"tile={label} elapsed={elapsed:.0f}s rate={rate:.1f} tiles/s "
                            f"eta={remaining:.0f}s decoded={len(decoded)}",
                            file=sys.stderr, flush=True,
                        )
                        last_progress = now
        if count == 0:
            raise RasterExecutionError("raster readback plan is empty")
        def sha512(path: str) -> str:
            with open(path, "rb") as stream:
                return hashlib.file_digest(stream, "sha512").hexdigest()
        document = {"schema_version": 1, "status": "passed", "verified_tiles": count,
                    "decoded_contents": len(decoded), "tile_size": tile_size,
                    "archive_sha512": sha512(archive), "queue_sha512": sha512(queue),
                    "visual_acceptance": "not-run", "client_installation": "not-run"}
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=report.parent, delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(document, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                temporary.replace(report)
            finally:
                temporary.unlink(missing_ok=True)
        return count
