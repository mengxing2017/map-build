from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
import tempfile
import threading

from huavd_map_build.production.domain.raster import (
    RasterBatchExecutionError,
    RasterNonRetryableError,
    RasterRenderBatchResult,
    RasterRenderResult,
    RasterRenderSettings,
    RasterTileCoordinate,
)
from huavd_map_build.production.south.port.raster import (
    RasterTileEncoder,
    RasterTileRenderer,
    RasterWorkQueue,
)


@dataclass(frozen=True, slots=True)
class _Batch:
    planned: int
    rendered: int
    failed: int
    samples: tuple[str, ...]
    exhausted: bool
    cause: Exception | None = None


class RasterRenderService:
    def __init__(
        self, queue: RasterWorkQueue, renderer: RasterTileRenderer,
        encoder: RasterTileEncoder,
    ) -> None:
        self._queue, self._renderer, self._encoder = queue, renderer, encoder

    def render(
        self, queue_path: str, settings: RasterRenderSettings,
        on_batch: Callable[[RasterRenderBatchResult], None] | None = None,
    ) -> RasterRenderResult:
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

        def batch_error(count: int, batch_samples: tuple[str, ...]) -> RasterBatchExecutionError:
            return RasterBatchExecutionError(count, batch_samples, {
                "worker_queue_tiles": planned, "rendered_tiles": rendered,
                "failed_tiles": count, "attempts": attempt_count,
                "retried_tiles": retry_count, "failure_counts": dict(failures),
                "exit_code_counts": dict(exit_codes),
            })

        coordinates = iter(self._queue.coordinates(queue_path))
        index = 0
        while True:
            batch = self._render_batch(coordinates, settings, record)
            if batch is None:
                break
            index += 1
            planned += batch.planned
            rendered += batch.rendered
            failed += batch.failed
            for sample in batch.samples:
                if len(samples) < 10:
                    samples.append(sample)
            if on_batch is not None:
                on_batch(RasterRenderBatchResult(
                    index, batch.planned, batch.rendered, batch.failed, batch.samples,
                ))
            if batch.failed:
                raise batch_error(failed, tuple(samples)) from batch.cause
            if batch.exhausted:
                break
        return RasterRenderResult(
            planned, rendered, attempt_count, retry_count,
            dict(failures), dict(exit_codes),
        )

    def _render_batch(
        self, coordinates: Iterator[RasterTileCoordinate],
        settings: RasterRenderSettings,
        record: Callable[[int, str, Exception | None], None],
    ) -> _Batch | None:
        limit = settings.batch_tiles
        try:
            preflight = next(coordinates)
        except StopIteration:
            return None
        planned = 1
        try:
            self._render_one(preflight, settings, record)
        except Exception as error:
            return _Batch(
                1, 0, 1,
                (f"{preflight.zoom}/{preflight.x}/{preflight.y}: {error}",), False,
                error,
            )
        rendered, failed = 1, 0
        samples: list[str] = []
        futures: dict[Future[tuple[int, int]], RasterTileCoordinate] = {}
        exhausted = False
        with ThreadPoolExecutor(max_workers=settings.parallel_jobs) as executor:
            try:
                while futures or not exhausted:
                    while (
                        not exhausted
                        and len(futures) < settings.parallel_jobs
                        and (limit is None or planned < limit)
                    ):
                        try:
                            coordinate = next(coordinates)
                        except StopIteration:
                            exhausted = True
                            break
                        planned += 1
                        futures[executor.submit(
                            self._render_one, coordinate, settings, record
                        )] = coordinate
                    if not futures:
                        break
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
        return _Batch(planned, rendered, failed, tuple(samples), exhausted)

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
