from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.catalog.domain.model import CatalogValidationError, RegionCatalog


@dataclass(frozen=True, slots=True)
class CatalogSnapshot:
    schema_version: int
    regions: tuple[dict[str, object], ...]

    @classmethod
    def from_catalog(cls, catalog: RegionCatalog) -> CatalogSnapshot:
        entries: list[dict[str, object]] = []
        for region in catalog.regions:
            roles = region.huavd.asset_roles or (None,)
            for role in roles:
                entries.append(cls._entry(catalog, region.id.value, role))
        return cls(int(catalog.schema_version), tuple(entries))

    @staticmethod
    def _entry(
        catalog: RegionCatalog, region_id: str, asset_role: str | None
    ) -> dict[str, object]:
        from huavd_map_build.shared.kernel import RegionId

        identity = RegionId(region_id)
        region = catalog.get(identity)
        parent = region.geofabrik.parent_region
        if region.huavd.region_id is None:
            raise CatalogValidationError(f"missing huavd.region_id for {identity}")
        entry: dict[str, object] = {
            "id": region.id.value,
            "slug": region.slug,
            "region_id": region.huavd.region_id,
            "depth": catalog.depth(identity),
            "asset_role": asset_role or catalog.inherited(identity, "asset_role") or "base-vector",
            "source_id": region.huavd.source_id
            or catalog.default_source_id_template.replace("{region_slug}", identity.slug),
            "source_type": catalog.inherited(identity, "source_type") or "osm-pbf",
            "style_id": catalog.inherited(identity, "style_id") or "osm-dev",
            "mapping_status": region.huavd.mapping_status
            or catalog.inherited(identity, "mapping_status")
            or "pending-source-id",
            "priority": region.priority,
            "deprecated": region.huavd.deprecated,
            "replacement_region_id": region.huavd.replacement_region_id,
            "display_name": region.display_name,
            "display_name_zh": region.display_name_zh or region.display_name,
        }
        if parent is not None:
            parent_region_id = catalog.get(parent).huavd.region_id
            if parent_region_id is None:
                raise CatalogValidationError(
                    f"missing parent huavd.region_id for {identity}"
                )
            entry["parent_region"] = parent_region_id
        defaults = {
            "asset_role": "base-vector",
            "source_type": "osm-pbf",
            "style_id": "osm-dev",
            "mapping_status": "pending-source-id",
            "priority": "global-skeleton",
            "deprecated": False,
            "replacement_region_id": None,
        }
        for key, value in defaults.items():
            if entry.get(key) == value:
                entry.pop(key, None)
        if entry["display_name_zh"] == entry["display_name"]:
            entry.pop("display_name_zh")
        if not entry.get("source_id"):
            entry.pop("source_id", None)
        return entry

    def as_dict(self) -> dict[str, object]:
        return {"schema_version": self.schema_version, "regions": list(self.regions)}
