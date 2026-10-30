from __future__ import annotations

from pathlib import Path

from huavd_map_build.catalog.domain import (
    GeofabrikSource,
    HuavdRegionSettings,
    Region,
    RegionCatalog,
)
from huavd_map_build.catalog.south.adapter.yaml.loader import (
    YamlAdapterError,
    PyYamlConfigurationRepository,
)
from huavd_map_build.shared.kernel import RegionId
from huavd_map_build.catalog.domain.model import RoutingSettings


class CatalogAdapterError(YamlAdapterError):
    """Raised when the YAML catalog cannot be decoded at the system boundary."""


class PyYamlRegionCatalogRepository:
    def __init__(self, catalog_path: Path) -> None:
        self._catalog_path = catalog_path
        self._loader = PyYamlConfigurationRepository(catalog_path.parent)

    def load(self) -> RegionCatalog:
        document = self._loader.load(self._catalog_path.stem)
        try:
            raw_regions = document["regions"]
            schema_version = str(document["schema_version"])
        except (KeyError, TypeError) as error:
            raise CatalogAdapterError("invalid regions catalog root structure") from error
        if not isinstance(raw_regions, list):
            raise CatalogAdapterError("regions catalog .regions must be an array")
        routing = self._routing(document.get("routing", {}))
        return RegionCatalog(
            schema_version=schema_version,
            regions=tuple(self._to_region(item, routing) for item in raw_regions),
            default_source_id_template=str(
                document.get("huavd", {}).get("default_source_id_template", "")
            ),
            source_id_template_per_role=tuple(
                document.get("huavd", {}).get("source_id_template_per_role", {}).items()
            ),
            default_package_version_template=str(
                document.get("huavd", {}).get(
                    "default_package_version_template", "{yyyymmdd}.{role}"
                )
            ),
            package_version_template_per_role=tuple(
                document.get("huavd", {})
                .get("package_version_template_per_role", {})
                .items()
            ),
        )

    @staticmethod
    def _routing(value: object, defaults: RoutingSettings | None = None) -> RoutingSettings:
        if not isinstance(value, dict) or set(value) - {"invalid_maxspeed", "invalid_restrictions", "max_load_bytes"}:
            raise CatalogAdapterError("routing must contain only supported routing fields")
        defaults = defaults or RoutingSettings()
        try:
            return RoutingSettings(
                max_load_bytes=value.get("max_load_bytes", defaults.max_load_bytes),
                invalid_maxspeed=value.get("invalid_maxspeed", defaults.invalid_maxspeed),
                invalid_restrictions=value.get("invalid_restrictions", defaults.invalid_restrictions),
            )
        except ValueError as error:
            raise CatalogAdapterError(str(error)) from error

    @staticmethod
    def _to_region(value: object, routing: RoutingSettings | None = None) -> Region:
        if not isinstance(value, dict):
            raise CatalogAdapterError("each region must be an object")
        try:
            geofabrik = value["geofabrik"]
            if not isinstance(geofabrik, dict):
                raise TypeError("geofabrik must be an object")
            parent_value = geofabrik.get("parent_region")
            parent = RegionId(str(parent_value)) if parent_value else None
            huavd = value.get("huavd")
            if not isinstance(huavd, dict):
                raise TypeError("huavd must be an object")
            return Region(
                id=RegionId(str(value["id"])),
                routing=PyYamlRegionCatalogRepository._routing(value.get("routing", {}), routing),
                slug=str(value["slug"]),
                display_name=str(value["display_name"]),
                display_name_zh=PyYamlRegionCatalogRepository._optional_string(
                    value.get("display_name_zh")
                ),
                priority=str(value["priority"]),
                direct_tippecanoe=bool(value["direct_tippecanoe"]),
                geofabrik=GeofabrikSource(
                    pbf_url=PyYamlRegionCatalogRepository._optional_string(
                        geofabrik.get("pbf_url")
                    ),
                    md5_url=PyYamlRegionCatalogRepository._optional_string(
                        geofabrik.get("md5_url")
                    ),
                    basename=PyYamlRegionCatalogRepository._optional_string(
                        geofabrik.get("basename")
                    ),
                    parent_region=parent,
                ),
                huavd=HuavdRegionSettings(
                    source_id=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("source_id")
                    ),
                    region_id=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("region_id")
                    ),
                    asset_role=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("asset_role")
                    ),
                    source_type=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("source_type")
                    ),
                    style_id=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("style_id")
                    ),
                    package_version_template=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("package_version_template")
                    ),
                    mapping_status=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("mapping_status")
                    ),
                    asset_roles=tuple(str(item) for item in huavd.get("asset_roles", ())),
                    deprecated=bool(huavd.get("deprecated", False)),
                    replacement_region_id=PyYamlRegionCatalogRepository._optional_string(
                        huavd.get("replacement_region_id")
                    ),
                    name_locale_priority=tuple(
                        str(item) for item in huavd.get("name_locale_priority", ())
                    ),
                ),
            )
        except (KeyError, TypeError, ValueError) as error:
            region_id = value.get("id", "<unknown>")
            raise CatalogAdapterError(f"invalid region entry {region_id}: {error}") from error

    @staticmethod
    def _optional_string(value: object) -> str | None:
        return None if value is None else str(value)
