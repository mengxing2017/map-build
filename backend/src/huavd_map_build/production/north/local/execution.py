from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from huavd_map_build.production.domain.orchestration import (
    BuildExecutionPlan,
    BuildJob,
    BuildStatus,
    StageStatus,
)
from huavd_map_build.production.south.port.orchestration import BuildStageExecutor
from huavd_map_build.shared.kernel import Role


@dataclass(frozen=True, slots=True)
class BuildExecutionError(RuntimeError):
    job: BuildJob
    cause: Exception

    def __str__(self) -> str:
        stage = next(
            (item.id for item in self.job.stages if item.status is StageStatus.FAILED),
            "unknown",
        )
        return f"build stage failed: {stage}: {self.cause}"


class BuildExecutionService:
    def __init__(
        self,
        executor: BuildStageExecutor,
        clock: Callable[[], str] | None = None,
        reporter: Callable[[str, str, int, int], None] | None = None,
    ) -> None:
        self._executor = executor
        self._clock = clock or self._utc_now
        self._reporter = reporter

    def run(self, plan: BuildExecutionPlan) -> BuildJob:
        if not plan.build.roles or any(
            role not in (Role.BASE, Role.BUILDING) for role in plan.build.roles
        ):
            raise ValueError(
                "region vector build execution supports base/building roles"
            )
        job = BuildJob.from_plan(plan, self._clock())
        total = len(job.stages)
        while job.status is not BuildStatus.SUCCEEDED:
            job = job.start_next(self._clock())
            stage = next(
                item for item in job.stages if item.status is StageStatus.RUNNING
            )
            index = next(
                value for value, item in enumerate(job.stages, 1)
                if item.status is StageStatus.RUNNING
            )
            self._report("start", stage.id, index, total)
            try:
                self._executor.execute(stage.id, plan.build)
            except Exception as error:
                self._report("fail", stage.id, index, total)
                failed = job.fail_current(self._clock(), str(error) or type(error).__name__)
                raise BuildExecutionError(failed, error) from error
            job = job.complete_current(self._clock())
            self._report("done", stage.id, index, total)
        return job

    def _report(self, status: str, stage: str, index: int, total: int) -> None:
        if self._reporter is not None:
            self._reporter(status, stage, index, total)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
