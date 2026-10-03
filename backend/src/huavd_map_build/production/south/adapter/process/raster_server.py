from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import socket
import subprocess
import time
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
    ) -> RasterMvtPreflightResult:
        url = tile_url.format(z=coordinate.zoom, x=coordinate.x, y=coordinate.y)
        started = time.perf_counter()
        try:
            with urlopen(url, timeout=self._timeout_seconds) as response:
                payload = response.read()
        except (OSError, URLError) as error:
            raise RasterExecutionError(f"failed to fetch MVT preflight tile {url}: {error}") from error
        if not payload:
            raise RasterExecutionError(f"empty MVT preflight response: {url}")
        return RasterMvtPreflightResult(
            url, len(payload), round((time.perf_counter() - started) * 1000, 3)
        )
