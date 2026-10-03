from dataclasses import dataclass

from huavd_map_build.catalog.domain import Region, RegionCatalog
from huavd_map_build.catalog.south.port.repository import RegionCatalogRepository
from huavd_map_build.shared.kernel import RegionId


@dataclass(frozen=True, slots=True)
class CatalogSummary:
    schema_version: str
    region_count: int


class CatalogService:
    def __init__(self, repository: RegionCatalogRepository) -> None:
        self._repository = repository
        self._catalog_snapshot: RegionCatalog | None = None

    def _catalog(self) -> RegionCatalog:
        if self._catalog_snapshot is None:
            self._catalog_snapshot = self._repository.load()
        return self._catalog_snapshot

    def validate(self) -> CatalogSummary:
        catalog = self._catalog()
        return CatalogSummary(catalog.schema_version, len(catalog.regions))

    def list_regions(self) -> tuple[Region, ...]:
        return self._catalog().regions

    def region(self, region: RegionId) -> Region:
        return self._catalog().get(region)

    def name_locale_priority(self, region: RegionId) -> tuple[str, ...]:
        return self._catalog().get(region).huavd.name_locale_priority

    def pbf_basename(self, region: RegionId) -> str:
        basename = self._catalog().get(region).geofabrik.basename
        if basename is None:
            raise ValueError(f"region lacks geofabrik.basename: {region}")
        return basename

    def pbf_url(self, region: RegionId) -> str:
        url = self._catalog().get(region).geofabrik.pbf_url
        if url is None:
            raise ValueError(f"region lacks geofabrik.pbf_url: {region}")
        return url

    def md5_url(self, region: RegionId) -> str:
        url = self._catalog().get(region).geofabrik.md5_url
        if url is None:
            raise ValueError(f"region lacks geofabrik.md5_url: {region}")
        return url

    def region_settings(
        self, region_id: RegionId, role: str, yyyymmdd: str
    ) -> dict[str, object]:
        catalog = self._catalog()
        region = catalog.get(region_id)
        asset_role = catalog.inherited(region_id, "asset_role")
        source_type = catalog.inherited(region_id, "source_type")
        return {
            "id": region.id.value,
            "slug": region.slug,
            "pbf_basename": region.geofabrik.basename,
            "source_id": catalog.source_id(region_id, role),
            "region_id": region.huavd.region_id,
            "style_id": catalog.inherited(region_id, "style_id") or "osm-dev",
            "asset_role": asset_role,
            "source_type": source_type,
            "building_enabled": (
                asset_role == "building-vector" and source_type == "derived-building"
            ),
            "package_version": catalog.package_version(region_id, role, yyyymmdd),
        }
