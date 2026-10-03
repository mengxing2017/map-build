from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from huavd_map_build.shared.kernel import RegionId


class CatalogValidationError(ValueError):
    """Raised when catalog data violates a catalog invariant."""


@dataclass(frozen=True, slots=True)
class GeofabrikSource:
    pbf_url: str | None
    md5_url: str | None
    basename: str | None
    parent_region: RegionId | None = None

    def __post_init__(self) -> None:
        if self.basename is None:
            return
        if not self.basename or "/" in self.basename:
            raise CatalogValidationError(
                f"invalid Geofabrik basename: {self.basename!r}"
            )
        if not self.basename.endswith(".osm.pbf"):
            raise CatalogValidationError(
                f"Geofabrik basename must end with .osm.pbf: {self.basename}"
            )


@dataclass(frozen=True, slots=True)
class HuavdRegionSettings:
    source_id: str | None
    region_id: str | None
    asset_role: str | None
    source_type: str | None
    style_id: str | None
    package_version_template: str | None
    mapping_status: str | None
    asset_roles: tuple[str, ...]
    deprecated: bool
    replacement_region_id: str | None
    name_locale_priority: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Region:
    id: RegionId
    slug: str
    display_name: str
    display_name_zh: str | None
    priority: str
    direct_tippecanoe: bool
    geofabrik: GeofabrikSource
    huavd: HuavdRegionSettings

    def __post_init__(self) -> None:
        if self.slug != self.id.slug:
            raise CatalogValidationError(
                f"region {self.id} slug {self.slug!r} does not match {self.id.slug!r}"
            )
        if not self.display_name:
            raise CatalogValidationError(f"region {self.id} has no display name")
        if not self.priority:
            raise CatalogValidationError(f"region {self.id} has no priority")


@dataclass(frozen=True, slots=True)
class RegionCatalog:
    schema_version: str
    regions: tuple[Region, ...]
    default_source_id_template: str
    source_id_template_per_role: tuple[tuple[str, str], ...]
    default_package_version_template: str
    package_version_template_per_role: tuple[tuple[str, str], ...]
    _regions_by_id: Mapping[str, Region] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise CatalogValidationError("regions catalog has no schema_version")
        ids = [region.id.value for region in self.regions]
        if len(ids) != len(set(ids)):
            raise CatalogValidationError("regions catalog contains duplicate region ids")
        object.__setattr__(
            self,
            "_regions_by_id",
            MappingProxyType({region.id.value: region for region in self.regions}),
        )

        known = set(ids)
        for region in self.regions:
            parent = region.geofabrik.parent_region
            if parent is not None and parent.value not in known:
                raise CatalogValidationError(
                    f"region {region.id} references unknown parent {parent}"
                )

    def get(self, region_id: RegionId) -> Region:
        try:
            return self._regions_by_id[region_id.value]
        except KeyError as error:
            raise CatalogValidationError(
                f"region is not configured: {region_id}"
            ) from error

    def inherited(self, region_id: RegionId, field: str) -> str | None:
        current = self.get(region_id)
        visited: set[RegionId] = set()
        while current.id not in visited:
            visited.add(current.id)
            value = getattr(current.huavd, field)
            if value is not None:
                return value
            parent = current.geofabrik.parent_region
            if parent is None:
                return None
            current = self.get(parent)
        raise CatalogValidationError(f"parent cycle detected for region: {region_id}")

    def source_id(self, region_id: RegionId, role: str) -> str | None:
        region = self.get(region_id)
        if region.huavd.source_id is not None:
            return region.huavd.source_id
        per_role = dict(self.source_id_template_per_role)
        template = per_role.get(role, self.default_source_id_template)
        if template:
            return template.replace("{region_slug}", region_id.slug)
        return self.inherited(region_id, "source_id")

    def package_version(self, region_id: RegionId, role: str, yyyymmdd: str) -> str:
        template = self.inherited(region_id, "package_version_template")
        if template is None:
            per_role = dict(self.package_version_template_per_role)
            template = per_role.get(role, self.default_package_version_template)
        if role in {"building", "dem"}:
            template = template.replace(".{yyyymmdd}", f"-{role}.{{yyyymmdd}}", 1)
        return template.replace("{yyyymmdd}", yyyymmdd).replace("{role}", role)

    def depth(self, region_id: RegionId) -> int:
        depth = 1
        current = self.get(region_id)
        visited: set[RegionId] = set()
        while current.geofabrik.parent_region is not None:
            if current.id in visited:
                raise CatalogValidationError(
                    f"parent cycle detected for region: {region_id}"
                )
            visited.add(current.id)
            current = self.get(current.geofabrik.parent_region)
            depth += 1
        return depth
