from dataclasses import dataclass

from huavd_map_build.shared.kernel import RegionId


class FetchToolError(RuntimeError):
    """Raised when download or source-integrity verification fails."""


@dataclass(frozen=True, slots=True)
class FetchRequest:
    region: RegionId
    workdir: str
    limit_rate: str = "10m"

    def __post_init__(self) -> None:
        if not self.workdir:
            raise ValueError("fetch workdir must not be empty")
        if not self.limit_rate:
            raise ValueError("fetch limit rate must not be empty")
