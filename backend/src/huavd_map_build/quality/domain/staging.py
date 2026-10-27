from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.quality.domain.coverage import SourceCoverage


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
    coverage: SourceCoverage | None = None

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        result = {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "checked_layers": list(self.checked_layers),
            "feature_count": self.feature_count,
            "findings": [finding.as_dict() for finding in self.findings],
        }
        if self.coverage is not None:
            result["low_zoom_coverage"] = self.coverage.as_dict()
        return result


@dataclass(frozen=True, slots=True)
class BaseDeepVerificationError(RuntimeError):
    report: BaseStagingQualityReport

    def __str__(self) -> str:
        return f"base staging quality gate failed with {len(self.report.findings)} finding(s)"
