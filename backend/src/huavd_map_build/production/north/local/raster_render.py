from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from pathlib import Path
import tempfile
import threading

from huavd_map_build.production.domain.raster import (
    RasterBatchExecutionError,
    RasterNonRetryableError,
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
        planned = rendered = failed = 0
        samples: list[str] = []
        attempt_count = retry_count = 0
        failures: Counter[str] = Counter()
        exit_codes: Counter[str] = Counter()
        lock = threading.Lock()

        def record(attempt: int, stage: str, error: Exception | None) -> None:
            nonlocal attempt_count, retry_count
            with lock:
                attempt_count += 1
                retry_count += int(attempt > 1)
                if error is not None:
                    category = "non-retryable" if isinstance(error, RasterNonRetryableError) else "retryable"
                    failures[f"{stage}:{category}"] += 1
                    code = getattr(error, "exit_code", None)
                    if code is not None:
                        exit_codes[str(code)] += 1

        def batch_error(count: int, samples: tuple[str, ...]) -> RasterBatchExecutionError:
            return RasterBatchExecutionError(count, samples, {
                "worker_queue_tiles": planned, "rendered_tiles": rendered,
                "failed_tiles": count, "attempts": attempt_count,
                "retried_tiles": retry_count, "failure_counts": dict(failures),
                "exit_code_counts": dict(exit_codes),
            })

        coordinates = iter(self._queue.coordinates(queue_path))
        try:
            preflight = next(coordinates)
        except StopIteration:
            return RasterRenderResult(0, 0, 0, 0)
        planned = 1
        try:
            self._render_one(preflight, settings, record)
        except Exception as error:
            raise batch_error(
                1, (f"{preflight.zoom}/{preflight.x}/{preflight.y}: {error}",)
            ) from error
        rendered = 1
        futures: dict[Future[tuple[int, int]], RasterTileCoordinate] = {}
        with ThreadPoolExecutor(max_workers=settings.parallel_jobs) as executor:
            try:
                exhausted = False
                while futures or not exhausted:
                    while not exhausted and len(futures) < settings.parallel_jobs:
                        try:
                            coordinate = next(coordinates)
                        except StopIteration:
                            exhausted = True
                            break
                        planned += 1
                        futures[executor.submit(self._render_one, coordinate, settings, record)] = coordinate
                    if not futures:
                        continue
                    completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in completed:
                        coordinate = futures.pop(future)
                        try:
                            future.result()
                        except Exception as error:
                            failed += 1
                            if len(samples) < 10:
                                samples.append(
                                    f"{coordinate.zoom}/{coordinate.x}/{coordinate.y}: {error}"
                                )
                        else:
                            rendered += 1
            except BaseException:
                # Cancel before executor shutdown waits for workers.
                cancel = getattr(self._renderer, "cancel", None)
                if cancel is not None:
                    cancel()
                for future in futures:
                    future.cancel()
                raise
        if failed:
            raise batch_error(failed, tuple(samples))
        return RasterRenderResult(planned, rendered, attempt_count, retry_count,
                                  dict(failures), dict(exit_codes))

    def _render_one(
        self, coordinate: RasterTileCoordinate, settings: RasterRenderSettings,
        record: Callable[[int, str, Exception | None], None] | None = None,
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
            stage = "render"
            error_seen = None
            try:
                self._renderer.render(coordinate, settings, str(png))
                stage = "encode"
                self._encoder.encode(str(png), str(webp), settings)
                return attempt, attempt - 1
            except RasterNonRetryableError as error:
                error_seen = error
                raise
            except Exception as error:
                error_seen = last_error = error
            finally:
                if record is not None:
                    record(attempt, stage, error_seen)
                png.unlink(missing_ok=True)
        assert last_error is not None
        raise last_error
