from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
import tempfile

from huavd_map_build.production.domain.raster import (
    RasterBatchExecutionError,
    RasterRenderResult,
    RasterRenderSettings,
    RasterTileCoordinate,
)
from huavd_map_build.production.south.port.raster import (
    RasterTileEncoder,
    RasterTileRenderer,
    RasterWorkQueue,
)


class RasterRenderService:
    def __init__(
        self, queue: RasterWorkQueue, renderer: RasterTileRenderer,
        encoder: RasterTileEncoder,
    ) -> None:
        self._queue, self._renderer, self._encoder = queue, renderer, encoder

    def render(self, queue_path: str, settings: RasterRenderSettings) -> RasterRenderResult:
        planned = rendered = attempts = retried = failed = 0
        samples: list[str] = []
        coordinates = iter(self._queue.coordinates(queue_path))
        futures: dict[Future[tuple[int, int]], RasterTileCoordinate] = {}
        with ThreadPoolExecutor(max_workers=settings.parallel_jobs) as executor:
            exhausted = False
            while futures or not exhausted:
                while not exhausted and len(futures) < settings.parallel_jobs:
                    try:
                        coordinate = next(coordinates)
                    except StopIteration:
                        exhausted = True
                        break
                    planned += 1
                    futures[executor.submit(self._render_one, coordinate, settings)] = coordinate
                if not futures:
                    continue
                completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                for future in completed:
                    coordinate = futures.pop(future)
                    try:
                        tile_attempts, tile_retries = future.result()
                    except Exception as error:
                        failed += 1
                        if len(samples) < 10:
                            samples.append(
                                f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}"
                            )
                    else:
                        rendered += 1
                        attempts += tile_attempts
                        retried += tile_retries
        if failed:
            raise RasterBatchExecutionError(failed, tuple(samples))
        return RasterRenderResult(planned, rendered, attempts, retried)

    def _render_one(
        self, coordinate: RasterTileCoordinate, settings: RasterRenderSettings,
    ) -> tuple[int, int]:
        png_parent = Path(settings.png_directory) / str(coordinate.zoom) / str(coordinate.x)
        webp = (
            Path(settings.webp_directory) / str(coordinate.zoom) /
            str(coordinate.x) / f"{coordinate.y}.webp"
        )
        png_parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(1, settings.retries + 2):
            with tempfile.NamedTemporaryFile(
                dir=png_parent, prefix=f".{coordinate.y}.", suffix=".png", delete=False,
            ) as output:
                png = Path(output.name)
            try:
                self._renderer.render(coordinate, settings, str(png))
                self._encoder.encode(str(png), str(webp), settings)
                return attempt, attempt - 1
            except Exception as error:
                last_error = error
            finally:
                png.unlink(missing_ok=True)
        assert last_error is not None
        raise last_error
