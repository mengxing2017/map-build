from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ToolHealth(StrEnum):
    OK = "ok"
    MISSING = "missing"
    NOT_RUNNABLE = "not-runnable"


@dataclass(frozen=True, slots=True)
class ToolRequirement:
    name: str
    python_module: str | None = None


@dataclass(frozen=True, slots=True)
class ToolStatus:
    name: str
    health: ToolHealth
    version: str | None = None
    executable: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    tools: tuple[ToolStatus, ...]
    catalog_schema_version: str | None
    catalog_region_count: int | None
    catalog_error: str | None

    @property
    def healthy(self) -> bool:
        return self.catalog_error is None and all(
            tool.health is ToolHealth.OK for tool in self.tools
        )

    @property
    def passed(self) -> bool:
        return self.catalog_error is None

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": (
                "failed"
                if not self.passed
                else "ok"
                if self.healthy
                else "warning"
            ),
            "catalog": {
                "schema_version": self.catalog_schema_version,
                "region_count": self.catalog_region_count,
                "error": self.catalog_error,
            },
            "tools": [
                {
                    "name": tool.name,
                    "status": tool.health.value,
                    "version": tool.version,
                    "executable": tool.executable,
                }
                for tool in self.tools
            ],
        }
