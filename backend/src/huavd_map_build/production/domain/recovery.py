from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ArtifactSetState(StrEnum):
    CLEAN = "clean"
    INCOMPLETE = "incomplete"
    COMPLETE = "complete"


@dataclass(frozen=True, slots=True)
class BuildPreparationResult:
    state: ArtifactSetState
    removed: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "previous_state": self.state.value,
            "removed": list(self.removed),
        }


class ExistingBuildArtifactsError(RuntimeError):
    pass
