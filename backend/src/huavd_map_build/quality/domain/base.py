from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.quality.domain.staging import BaseStagingQualityReport
from huavd_map_build.quality.domain.tile import TileSamplingReport


@dataclass(frozen=True, slots=True)
class BaseDeepQualityReport:
    staging: BaseStagingQualityReport
    tiles: TileSamplingReport

    @property
    def passed(self) -> bool:
        return self.staging.passed and self.tiles.passed

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "staging": self.staging.as_dict(),
            "tiles": self.tiles.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class BaseDeepQualityError(RuntimeError):
    report: BaseDeepQualityReport

    def __str__(self) -> str:
        findings = (*self.report.staging.findings, *self.report.tiles.findings)
        count = len(findings)
        preview = "; ".join(
            f"{finding.code}: {finding.detail}" for finding in findings[:3]
        )
        suffix = f": {preview}" if preview else ""
        return f"base deep quality gate failed with {count} finding(s){suffix}"
