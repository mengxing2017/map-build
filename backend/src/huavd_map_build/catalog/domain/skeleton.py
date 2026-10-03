from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Iterable, Mapping, Sequence

from huavd_map_build.catalog.domain.model import CatalogValidationError


CONTINENT_IDS = (
    "africa",
    "antarctica",
    "asia",
    "australia-oceania",
    "europe",
    "north-america",
    "south-america",
)

CONTINENTS = {
    "africa": ("Africa", "africa", "un-002-base"),
    "antarctica": ("Antarctica", "antarctica", "aq-base"),
    "asia": ("Asia", "asia", "un-142-base"),
    "australia-oceania": ("Australia / Oceania", "australia-oceania", "un-009-base"),
    "europe": ("Europe", "europe", "un-150-base"),
    "north-america": ("North America", "north-america", "un-003-base"),
    "south-america": ("South America", "south-america", "un-005-base"),
}

COUNTRY_ID_OVERRIDES = {
    "AQ": "antarctica",
    "CN": "china",
    "ID": "indonesia",
    "IN": "india",
    "JP": "japan",
    "MO": "china/macau",
    "PH": "philippines",
    "RU": "russia",
    "TH": "thailand",
    "TW": "china/taiwan",
}

SUBDIVISION_ID_OVERRIDES = {
    "CN-44": "china/guangdong",
    "CN-45": "china/guangxi",
    "CN-53": "china/yunnan",
}

COUNTRY_PARENT_OVERRIDES = {"MO": "china", "TW": "china"}
COUNTRY_REGION_ID_OVERRIDES = {"MO": "cn-92-base", "TW": "cn-71-base"}
SUBDIVISION_COUNTRY_EXCLUDES = frozenset({"MO"})


def slugify(value: str) -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower().replace("&", " and "))
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "unnamed"


def stable_id_from_iso(code: str) -> str:
    parts = code.lower().replace("_", "-").split("-")
    normalized = [parts[0], *(part.zfill(2) if len(part) == 1 else part for part in parts[1:])]
    return f"{'-'.join(normalized)}-base"


def unique_stable_id_from_iso(
    code: str, name: str, used_region_ids: set[str]
) -> str:
    candidate = stable_id_from_iso(code)
    if candidate in used_region_ids:
        stem = candidate.removesuffix("-base")
        name_slug = slugify(name)
        candidate = f"{stem}-{name_slug}-base"
        index = 2
        while candidate in used_region_ids:
            candidate = f"{stem}-{name_slug}-{index}-base"
            index += 1
    used_region_ids.add(candidate)
    return candidate


@dataclass(frozen=True, slots=True)
class IsoCountry:
    code: str
    name: str


@dataclass(frozen=True, slots=True)
class IsoSubdivision:
    key: str
    level: int
    country_code: str
    code: str
    name: str
    parent_key: str


@dataclass(frozen=True, slots=True)
class IsoHierarchy:
    countries: tuple[IsoCountry, ...]
    subdivisions: tuple[IsoSubdivision, ...]

    @classmethod
    def parse(cls, rows: Iterable[Sequence[str]]) -> IsoHierarchy:
        countries: list[IsoCountry] = []
        subdivisions: list[IsoSubdivision] = []
        current_country: str | None = None
        current_admin1: str | None = None
        current_admin1_key: str | None = None
        for raw_row in rows:
            row = [str(value).strip() for value in raw_row]
            row.extend([""] * (4 - len(row)))
            country_code, admin1_code, admin2_code, name = row[:4]
            if country_code:
                current_country = country_code
                current_admin1 = None
                current_admin1_key = None
                countries.append(IsoCountry(country_code, name))
            elif admin1_code:
                if current_country is None:
                    raise CatalogValidationError(
                        f"subdivision without country at {admin1_code}"
                    )
                current_admin1 = admin1_code
                current_admin1_key = f"{admin1_code}@{len(subdivisions)}"
                subdivisions.append(
                    IsoSubdivision(
                        current_admin1_key,
                        1,
                        current_country,
                        admin1_code,
                        name,
                        current_country,
                    )
                )
            elif admin2_code:
                if not current_country or not current_admin1 or not current_admin1_key:
                    raise CatalogValidationError(
                        f"nested subdivision without admin-1 at {admin2_code}"
                    )
                subdivisions.append(
                    IsoSubdivision(
                        f"{admin2_code}@{len(subdivisions)}",
                        2,
                        current_country,
                        admin2_code,
                        name,
                        current_admin1_key,
                    )
                )
        return cls(tuple(countries), tuple(subdivisions))


@dataclass(frozen=True, slots=True)
class SkeletonIds:
    country_ids: Mapping[str, str]
    subdivision_ids: Mapping[str, str]

    @classmethod
    def plan(cls, hierarchy: IsoHierarchy) -> SkeletonIds:
        used_ids = set(CONTINENT_IDS)
        country_ids: dict[str, str] = {}
        for country in hierarchy.countries:
            base = COUNTRY_ID_OVERRIDES.get(country.code, slugify(country.name))
            identity = base
            index = 1
            while identity in used_ids and not (
                country.code == "AQ" and identity == "antarctica"
            ):
                suffix = country.code.lower()
                identity = f"{base}-{suffix}" if index == 1 else f"{base}-{suffix}-{index}"
                index += 1
            used_ids.add(identity)
            country_ids[country.code] = identity

        subdivision_ids: dict[str, str] = {}
        for subdivision in hierarchy.subdivisions:
            if subdivision.level == 1:
                parent_id = country_ids[subdivision.country_code]
            else:
                parent_id = subdivision_ids[subdivision.parent_key]
            base = SUBDIVISION_ID_OVERRIDES.get(
                subdivision.code, f"{parent_id}/{slugify(subdivision.name)}"
            )
            identity = base
            suffix = subdivision.code.split("-", 1)[-1].lower()
            index = 1
            while identity in used_ids:
                identity = f"{base}-{suffix}" if index == 1 else f"{base}-{suffix}-{index}"
                index += 1
            used_ids.add(identity)
            subdivision_ids[subdivision.key] = identity
        return cls(
            MappingProxyType(country_ids), MappingProxyType(subdivision_ids)
        )
