from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse


class AttributionContractError(ValueError):
    """Raised when attribution input cannot satisfy the delivery contract."""


@dataclass(frozen=True, slots=True)
class AttributionSource:
    vendor: str
    url: str | None

    def __post_init__(self) -> None:
        if self.url is not None:
            if not isinstance(self.url, str):
                raise AttributionContractError("attribution source URL must be a string or null")
            parsed = urlparse(self.url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise AttributionContractError(
                    f"invalid attribution source URL: {self.url}"
                )
        if not self.vendor:
            raise AttributionContractError("attribution source vendor is required")
        if self.vendor == "geofabrik" and self.url is None:
            raise AttributionContractError("Geofabrik attribution requires a URL")
        if self.vendor == "local" and self.url is not None:
            raise AttributionContractError("local attribution must have a null URL")

    def as_dict(self) -> dict[str, str | None]:
        return {"vendor": self.vendor, "url": self.url}


@dataclass(frozen=True, slots=True)
class AttributionDocument:
    data_license: str
    attribution: str
    sources: tuple[AttributionSource, ...]

    @classmethod
    def geofabrik_osm(cls, pbf_url: str | None) -> AttributionDocument:
        vendor = "geofabrik" if pbf_url else "local"
        return cls.osm(vendor, pbf_url)

    @classmethod
    def osm(cls, vendor: str, url: str | None) -> AttributionDocument:
        if vendor not in ("local", "geofabrik"):
            raise AttributionContractError(f"unsupported OSM source vendor: {vendor}")
        return cls(
            data_license="ODbL-1.0",
            attribution="© OpenStreetMap contributors",
            sources=(AttributionSource(vendor, url),),
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
