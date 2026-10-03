from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class DomainValidationError(ValueError):
    """Raised when a domain value cannot satisfy its invariant."""


_REGION_ID = re.compile(r"^[a-z0-9]+(?:[/-][a-z0-9]+)*$")
_BUILD_DATE = re.compile(r"^[0-9]{8}$")
_SESSION_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*-[0-9]{8}$")


@dataclass(frozen=True, slots=True)
class RegionId:
    value: str

    def __post_init__(self) -> None:
        if not _REGION_ID.fullmatch(self.value):
            raise DomainValidationError(f"invalid region id: {self.value}")

    @property
    def slug(self) -> str:
        return self.value.replace("/", "-")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class BuildDate:
    value: str

    def __post_init__(self) -> None:
        if not _BUILD_DATE.fullmatch(self.value):
            raise DomainValidationError(
                f"invalid YYYYMMDD: {self.value}; expected 8 digits like 20260818"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SessionId:
    value: str

    def __post_init__(self) -> None:
        if not _SESSION_ID.fullmatch(self.value):
            raise DomainValidationError(
                "invalid session id: expected {region-slug}-{yyyymmdd}"
            )

    @classmethod
    def for_build(cls, region: RegionId, build_date: BuildDate) -> SessionId:
        return cls(f"{region.slug}-{build_date.value}")

    def __str__(self) -> str:
        return self.value


class Role(StrEnum):
    BASE = "base"
    BUILDING = "building"
    RASTER_BAKE = "raster_bake"
    DEM = "dem"


ROLE_EXPANSIONS: dict[str, tuple[Role, ...]] = {
    "base": (Role.BASE,),
    "building": (Role.BUILDING,),
    "raster_bake": (Role.RASTER_BAKE,),
    "base_raster": (Role.BASE, Role.RASTER_BAKE),
    "both_raster": (Role.BASE, Role.BUILDING, Role.RASTER_BAKE),
    "both": (Role.BASE, Role.BUILDING),
    "dem": (Role.DEM,),
    "all": (Role.BASE, Role.BUILDING, Role.DEM),
}


def expand_roles(value: str) -> tuple[Role, ...]:
    try:
        return ROLE_EXPANSIONS[value]
    except KeyError as error:
        expected = ", ".join(ROLE_EXPANSIONS)
        raise DomainValidationError(
            f"invalid role: {value}; expected {expected}"
        ) from error
