from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.shared.kernel import Role


class BuildStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class StageStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class BuildStage:
    id: str
    status: StageStatus = StageStatus.PENDING


@dataclass(frozen=True, slots=True)
class BuildExecutionPlan:
    build: BuildPlan
    stages: tuple[BuildStage, ...]
    skipped_roles: tuple[Role, ...] = ()

    def as_dict(self) -> dict[str, object]:
        result = self.build.as_dict()
        result["stages"] = [stage.id for stage in self.stages]
        result["skipped_roles"] = [role.value for role in self.skipped_roles]
        return result


@dataclass(frozen=True, slots=True)
class BuildEvent:
    schema_version: str
    sequence: int
    session_id: str
    type: str
    stage: str | None
    occurred_at: str
    message: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "sequence": self.sequence,
            "session_id": self.session_id,
            "type": self.type,
            "stage": self.stage,
            "occurred_at": self.occurred_at,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class BuildJob:
    session_id: str
    stages: tuple[BuildStage, ...]
    status: BuildStatus = BuildStatus.PLANNED
    events: tuple[BuildEvent, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "session_id": self.session_id,
            "status": self.status.value,
            "stages": [
                {"id": stage.id, "status": stage.status.value}
                for stage in self.stages
            ],
            "events": [event.as_dict() for event in self.events],
        }

    @classmethod
    def from_plan(cls, plan: BuildExecutionPlan, occurred_at: str) -> BuildJob:
        if not plan.stages:
            raise ValueError("build execution plan has no stages")
        event = BuildEvent(
            "1", 1, plan.build.session.value, "BuildPlanned", None, occurred_at
        )
        return cls(plan.build.session.value, plan.stages, events=(event,))

    def start_next(self, occurred_at: str) -> BuildJob:
        if self.status not in (BuildStatus.PLANNED, BuildStatus.RUNNING):
            raise ValueError(f"cannot start stage when build is {self.status}")
        if any(stage.status is StageStatus.RUNNING for stage in self.stages):
            raise ValueError("a build stage is already running")
        index = next(
            (index for index, stage in enumerate(self.stages)
             if stage.status is StageStatus.PENDING), None
        )
        if index is None:
            raise ValueError("build has no pending stage")
        stages = list(self.stages)
        stages[index] = replace(stages[index], status=StageStatus.RUNNING)
        return self._transition(
            tuple(stages), BuildStatus.RUNNING, "StageStarted",
            stages[index].id, occurred_at,
        )

    def complete_current(self, occurred_at: str) -> BuildJob:
        index = self._running_index()
        stages = list(self.stages)
        stages[index] = replace(stages[index], status=StageStatus.SUCCEEDED)
        status = (
            BuildStatus.SUCCEEDED
            if all(stage.status is StageStatus.SUCCEEDED for stage in stages)
            else BuildStatus.RUNNING
        )
        completed = self._transition(
            tuple(stages), status, "StageCompleted", stages[index].id, occurred_at
        )
        if status is BuildStatus.SUCCEEDED:
            return completed._transition(
                tuple(stages), status, "BuildSucceeded", stages[index].id, occurred_at
            )
        return completed

    def fail_current(self, occurred_at: str, message: str) -> BuildJob:
        if not message:
            raise ValueError("build failure requires a message")
        index = self._running_index()
        stages = list(self.stages)
        stages[index] = replace(stages[index], status=StageStatus.FAILED)
        return self._transition(
            tuple(stages), BuildStatus.FAILED, "BuildFailed",
            stages[index].id, occurred_at, message,
        )

    def _running_index(self) -> int:
        indexes = [
            index for index, stage in enumerate(self.stages)
            if stage.status is StageStatus.RUNNING
        ]
        if len(indexes) != 1:
            raise ValueError("build must have exactly one running stage")
        return indexes[0]

    def _transition(
        self, stages: tuple[BuildStage, ...], status: BuildStatus,
        event_type: str, stage: str, occurred_at: str, message: str | None = None,
    ) -> BuildJob:
        event = BuildEvent(
            "1", len(self.events) + 1, self.session_id, event_type,
            stage, occurred_at, message,
        )
        return BuildJob(self.session_id, stages, status, (*self.events, event))


def create_execution_plan(
    build: BuildPlan,
    layers: tuple[str, ...],
    glyph: bool,
    has_profile: bool,
    skipped_roles: tuple[Role, ...] = (),
) -> BuildExecutionPlan:
    roles = tuple(role for role in build.roles if role not in skipped_roles)
    if Role.DEM in roles:
        raise ValueError("dem role uses the separate DEM build workflow")
    outputs = tuple(
        output for role, output in zip(build.roles, build.output_paths, strict=True)
        if role not in skipped_roles
    )
    vector_roles = tuple(role for role in roles if role in (Role.BASE, Role.BUILDING))
    raster = Role.RASTER_BAKE in roles
    if not roles:
        raise ValueError("no buildable roles")
    if raster and not glyph:
        raise ValueError("raster_bake requires glyph generation")
    stages: list[str] = []
    if raster and Role.BASE not in vector_roles:
        stages.append("verify-existing-base")
    if vector_roles:
        stages.extend(("source-link", "tags-filter", "export", "normalize"))
        if Role.BASE in vector_roles and "place_label" in layers:
            stages.append("place-admin-enrich")
        if "admin_line" in layers:
            stages.append("admin-line-tier")
        if Role.BASE in vector_roles and has_profile:
            stages.append("profile-transform")
        # Derivation reports fingerprint the final water input, including zoom policy.
        if "island" in layers and "water" in layers:
            stages.append("island-water-flag")
        if "island" in layers:
            stages.append("island-anchor")
        for role in vector_roles:
            stages.extend((
                f"tippecanoe:{role.value}",
                f"finalize-vector:{role.value}",
            ))
            if role is Role.BASE:
                stages.append("deep-verify:base")
    if glyph:
        stages.append("glyph")
        stages.append("sprite")
    if raster or glyph:
        stages.append("style")
        stages.append("style-quality")
    if raster:
        stages.append("raster-bake")
    return BuildExecutionPlan(
        replace(build, roles=roles, output_paths=outputs),
        tuple(BuildStage(stage) for stage in stages),
        skipped_roles,
    )
