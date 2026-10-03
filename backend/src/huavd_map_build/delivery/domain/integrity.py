from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntegrityFailure:
    code: str
    path: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class ArtifactIntegrityReport:
    checked_paths: tuple[str, ...]
    failures: tuple[IntegrityFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "checked_paths": list(self.checked_paths),
            "failures": [failure.as_dict() for failure in self.failures],
        }
