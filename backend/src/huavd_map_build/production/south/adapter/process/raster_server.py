from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import socket
import subprocess
import time
import zlib
from urllib.error import URLError
from urllib.request import urlopen

from huavd_map_build.production.domain.raster import (
    RasterExecutionError,
    RasterMvtPreflightResult,
    RasterTileCoordinate,
    RasterTileServerEndpoint,
)
from huavd_map_build.production.south.adapter.process.raster import (
    _environment,
    _executable,
)


class ProcessRasterTileServer:
    def __init__(self, startup_timeout_seconds: float = 10.0) -> None:
        self._startup_timeout_seconds = startup_timeout_seconds

    @contextmanager
    def open(self, archive_path: str):
        archive = Path(archive_path)
        if not archive.is_file():
            raise RasterExecutionError(f"PMTiles archive does not exist: {archive}")
        port = self._available_port()
        log_path = archive.with_name(f".{archive.name}.serve.log")
        log = log_path.open("wb")
        process: subprocess.Popen[bytes] | None = None
        try:
            try:
                process = subprocess.Popen(
                    [
                        _executable("pmtiles"), "serve", str(archive.parent),
                        "--interface=127.0.0.1", f"--port={port}",
                    ],
                    env=_environment(), stdout=log, stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
            except OSError as error:
                raise RasterExecutionError(
                    f"failed to start pmtiles serve: {error}"
                ) from error
            self._wait_until_ready(process, port, log_path)
            archive_name = archive.name.removesuffix(".pmtiles")
            yield RasterTileServerEndpoint(
                f"http://127.0.0.1:{port}/{archive_name}/{{z}}/{{x}}/{{y}}.mvt",
                port,
            )
        finally:
            if process is not None and process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
            log.close()

    def _wait_until_ready(
        self, process: subprocess.Popen[bytes], port: int, log_path: Path,
    ) -> None:
        deadline = time.monotonic() + self._startup_timeout_seconds
        while time.monotonic() < deadline:
            return_code = process.poll()
            if return_code is not None:
                raise RasterExecutionError(
                    f"pmtiles serve exited with code {return_code}; see {log_path}"
                )
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    return
            except OSError:
                time.sleep(0.05)
        raise RasterExecutionError(f"pmtiles serve startup timed out; see {log_path}")

    @staticmethod
    def _available_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])


class UrlLibRasterMvtClient:
    def __init__(self, timeout_seconds: float = 5.0) -> None:
        self._timeout_seconds = timeout_seconds

    def fetch(
        self, tile_url: str, coordinate: RasterTileCoordinate,
        validate: bool = False,
    ) -> RasterMvtPreflightResult:
        url = tile_url.format(z=coordinate.zoom, x=coordinate.x, y=coordinate.y)
        started = time.perf_counter()
        try:
            with urlopen(url, timeout=self._timeout_seconds) as response:
                payload = response.read(16 * 1024 * 1024 + 1) if validate else response.read()
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip()
                status = response.status
        except (OSError, URLError) as error:
            raise RasterExecutionError(f"failed to fetch MVT preflight tile {url}: {error}") from error
        if not payload and not (validate and (status == 204 or content_type in (
            "application/vnd.mapbox-vector-tile", "application/x-protobuf",
        ))):
            raise RasterExecutionError(f"empty MVT preflight response: {url}")
        if validate and payload:
            try:
                if len(payload) > 16 * 1024 * 1024:
                    raise ValueError("MVT exceeds size limit")
                decoded = payload
                if payload.startswith(b"\x1f\x8b"):
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
                    decoded = decoder.decompress(payload, 16 * 1024 * 1024 + 1)
                    if not decoder.eof or decoder.unused_data or len(decoded) > 16 * 1024 * 1024:
                        raise ValueError("invalid or oversized gzip MVT")
                import mapbox_vector_tile

                mapbox_vector_tile.decode(decoded)
            except Exception as error:
                raise RasterExecutionError(f"invalid MVT preflight response {url}: {error}") from error
        return RasterMvtPreflightResult(
            url, len(payload), round((time.perf_counter() - started) * 1000, 3)
        )
