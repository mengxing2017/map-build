from __future__ import annotations

from copy import deepcopy
from typing import Any

from huavd_map_build.catalog.domain.model import CatalogValidationError
from huavd_map_build.catalog.domain.skeleton import (
    CONTINENTS,
    COUNTRY_PARENT_OVERRIDES,
    COUNTRY_REGION_ID_OVERRIDES,
    SUBDIVISION_COUNTRY_EXCLUDES,
    IsoHierarchy,
    SkeletonIds,
    unique_stable_id_from_iso,
)
from huavd_map_build.catalog.south.port.skeleton import SkeletonSource


DEFAULT_VERSION = "{yyyymmdd}.{role}"


class RegionSkeletonService:
    def __init__(self, source: SkeletonSource) -> None:
        self._source = source

    @staticmethod
    def _continent_entry(identity: str, existing: dict[str, Any] | None) -> dict[str, Any]:
        name, url_slug, region_id = CONTINENTS[identity]
        entry = deepcopy(existing) if existing else {}
        entry.update(id=identity, slug=identity)
        entry.setdefault("display_name", name)
        entry.setdefault("priority", "split-source")
        entry["direct_tippecanoe"] = False
        geofabrik = entry.setdefault("geofabrik", {})
        geofabrik.setdefault("pbf_url", f"https://download.geofabrik.de/{url_slug}-latest.osm.pbf")
        geofabrik.setdefault("md5_url", f"https://download.geofabrik.de/{url_slug}-latest.osm.pbf.md5")
        geofabrik.setdefault("basename", f"{url_slug}-latest.osm.pbf")
        geofabrik["parent_region"] = None
        geofabrik["fallback"] = None
        huavd = entry.setdefault("huavd", {})
        huavd.setdefault("region_id", region_id)
        huavd.setdefault("source_id", None)
        huavd.setdefault("mapping_status", "not-direct-pmtiles")
        huavd.setdefault("asset_role", "base-vector")
        huavd.setdefault("source_type", "osm-pbf")
        huavd.setdefault("style_id", "osm-dev")
        huavd.setdefault("package_version_template", DEFAULT_VERSION)
        return entry

    @staticmethod
    def _skeleton(identity: str, name: str, parent: str, region_id: str) -> dict[str, Any]:
        return {
            "id": identity, "slug": identity.replace("/", "-"), "display_name": name,
            "priority": "global-skeleton", "direct_tippecanoe": True,
            "geofabrik": {"pbf_url": None, "md5_url": None, "basename": None,
                           "parent_region": parent, "fallback": None},
            "huavd": {"region_id": region_id, "source_id": None,
                      "mapping_status": "pending-source-id",
                      "package_version_template": DEFAULT_VERSION},
        }

    @staticmethod
    def _merge(existing: dict[str, Any] | None, generated: dict[str, Any]) -> dict[str, Any]:
        if existing is None:
            return deepcopy(generated)
        merged = deepcopy(existing)
        for key in ("slug", "display_name", "priority", "direct_tippecanoe"):
            merged.setdefault(key, generated[key])
        geofabrik = merged.setdefault("geofabrik", {})
        for key, value in generated["geofabrik"].items():
            geofabrik.setdefault(key, value)
        if geofabrik.get("parent_region") is None:
            geofabrik["parent_region"] = generated["geofabrik"]["parent_region"]
        huavd = merged.setdefault("huavd", {})
        if merged["priority"] == "global-skeleton":
            huavd["region_id"] = generated["huavd"]["region_id"]
        else:
            huavd.setdefault("region_id", generated["huavd"]["region_id"])
        huavd.setdefault("source_id", None)
        huavd.setdefault("mapping_status", generated["huavd"]["mapping_status"])
        huavd.setdefault("package_version_template", DEFAULT_VERSION)
        return merged

    def generate(self, iso_csv: str, existing_config: str) -> dict[str, Any]:
        config = self._source.yaml_document(existing_config)
        hierarchy = IsoHierarchy.parse(self._source.csv_rows(iso_csv))
        identities = SkeletonIds.plan(hierarchy)
        existing = {item["id"]: item for item in config.get("regions", [])}
        generated: dict[str, dict[str, Any]] = {
            identity: self._continent_entry(identity, existing.get(identity))
            for identity in CONTINENTS
        }
        used_region_ids = {spec[2] for spec in CONTINENTS.values()}
        country_region_ids: dict[str, str] = {}
        continents = self._source.country_continents()
        for country in hierarchy.countries:
            if country.code == "AQ":
                continue
            parent = COUNTRY_PARENT_OVERRIDES.get(country.code, continents.get(country.code))
            if not parent:
                raise CatalogValidationError(
                    f"country has no continent mapping: {country.code} {country.name}"
                )
            if country.code in COUNTRY_REGION_ID_OVERRIDES:
                region_id = COUNTRY_REGION_ID_OVERRIDES[country.code]
                if region_id in used_region_ids:
                    raise CatalogValidationError(f"duplicate region_id override: {region_id}")
                used_region_ids.add(region_id)
            else:
                region_id = unique_stable_id_from_iso(country.code, country.name, used_region_ids)
            country_region_ids[country.code] = region_id
            identity = identities.country_ids[country.code]
            generated[identity] = self._skeleton(identity, country.name, parent, region_id)
        subdivision_region_ids: dict[str, str] = {}
        for item in hierarchy.subdivisions:
            if item.country_code in SUBDIVISION_COUNTRY_EXCLUDES:
                continue
            parent = (identities.country_ids[item.country_code] if item.level == 1
                      else identities.subdivision_ids[item.parent_key])
            region_id = unique_stable_id_from_iso(item.code, item.name, used_region_ids)
            subdivision_region_ids[item.key] = region_id
            identity = identities.subdivision_ids[item.key]
            generated[identity] = self._skeleton(identity, item.name, parent, region_id)

        naming = config.setdefault("naming", {})
        naming["max_depth"] = 4
        naming["depth_segment_pattern"] = "^[a-z0-9]([a-z0-9-]*[a-z0-9])?$"
        naming.setdefault("region_slug_examples", {})[
            "china/guangxi/nanning"
        ] = "china-guangxi-nanning"
        merged = {
            identity: (
                self._continent_entry(identity, existing.get(identity))
                if identity in CONTINENTS
                else self._merge(existing.get(identity), entry)
            )
            for identity, entry in generated.items()
        }
        for identity, entry in existing.items():
            merged.setdefault(identity, entry)
        ordered: list[dict[str, Any]] = [merged[identity] for identity in CONTINENTS]
        for country in hierarchy.countries:
            if country.code != "AQ":
                ordered.append(merged[identities.country_ids[country.code]])
            for item in hierarchy.subdivisions:
                if item.country_code == country.code and item.country_code not in SUBDIVISION_COUNTRY_EXCLUDES:
                    ordered.append(merged[identities.subdivision_ids[item.key]])
        seen = {item["id"] for item in ordered}
        ordered.extend(entry for identity, entry in existing.items() if identity not in seen)
        config["regions"] = ordered
        return config

    def write(self, iso_csv: str, existing_config: str, output: str) -> None:
        self._source.write_yaml(output, self.generate(iso_csv, existing_config))

    def render_new(self, iso_csv: str, existing_config: str) -> str:
        existing_document = self._source.yaml_document(existing_config)
        existing_ids = {
            item["id"] for item in existing_document.get("regions", [])
        }
        generated = self.generate(iso_csv, existing_config)
        skeletons = [
            item for item in generated["regions"] if item["id"] not in existing_ids
        ]
        return self._source.render_yaml(skeletons)
