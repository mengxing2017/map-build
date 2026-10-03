from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StagingFinding:
    code: str
    layer: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "layer": self.layer, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class BaseStagingQualityReport:
    checked_layers: tuple[str, ...]
    feature_count: int
    findings: tuple[StagingFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "checked_layers": list(self.checked_layers),
            "feature_count": self.feature_count,
            "findings": [finding.as_dict() for finding in self.findings],
        }


@dataclass(frozen=True, slots=True)
class BaseDeepVerificationError(RuntimeError):
    report: BaseStagingQualityReport

    def __str__(self) -> str:
        return f"base staging quality gate failed with {len(self.report.findings)} finding(s)"
