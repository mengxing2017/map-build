from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class AttributionContractError(ValueError):
    """Raised when attribution input cannot satisfy the delivery contract."""


@dataclass(frozen=True, slots=True)
class AttributionSource:
    vendor: str
    url: str

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise AttributionContractError(f"invalid attribution source URL: {self.url}")
        if not self.vendor:
            raise AttributionContractError("attribution source vendor is required")

    def as_dict(self) -> dict[str, str]:
        return {"vendor": self.vendor, "url": self.url}


@dataclass(frozen=True, slots=True)
class AttributionDocument:
    data_license: str
    attribution: str
    sources: tuple[AttributionSource, ...]

    @classmethod
    def geofabrik_osm(cls, pbf_url: str) -> AttributionDocument:
        return cls(
            data_license="ODbL-1.0",
            attribution="© OpenStreetMap contributors",
            sources=(AttributionSource("geofabrik", pbf_url),),
        )

    def __post_init__(self) -> None:
        if not self.data_license or not self.attribution or not self.sources:
            raise AttributionContractError("attribution document is incomplete")

    def as_dict(self) -> dict[str, object]:
        return {
            "data_license": self.data_license,
            "attribution": self.attribution,
            "sources": [source.as_dict() for source in self.sources],
        }
