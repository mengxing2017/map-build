from dataclasses import dataclass
from typing import Any

from huavd_map_build.catalog.domain.configuration import (
    ConfigurationFinding,
    apply_tier_profile,
    inspect_layer_export_contracts,
    resolve_raster_bake,
    resolve_tippecanoe,
    resolve_vector_layers,
)
from huavd_map_build.catalog.south.port.configuration import ConfigurationRepository


@dataclass(frozen=True, slots=True)
class ConfigurationSummary:
    layer_count: int
    tier_profile_count: int
    schema_versions: tuple[tuple[str, str], ...]


class BuildConfigurationService:
    def __init__(self, repository: ConfigurationRepository) -> None:
        self._repository = repository

    def tippecanoe(self, region: str, role: str) -> dict[str, Any]:
        resolved = resolve_tippecanoe(
            self._repository.load("tippecanoe"), region, role
        )
        return apply_tier_profile(
            resolved,
            self._repository.load("tier-profiles"),
            self._repository.load("layers"),
            region,
            role,
        )

    def raster_bake(self, region: str) -> dict[str, Any]:
        return resolve_raster_bake(self._repository.load("bake"), region)

    def tags_filter_layers(
        self, selection: str
    ) -> tuple[tuple[str, tuple[str, ...]], ...]:
        layers = self._repository.load("layers").get("source_layers")
        if not isinstance(layers, dict) or not layers:
            raise ValueError("layers.yaml source_layers must be a non-empty object")
        if selection == "all":
            try:
                names = sorted(layers, key=lambda name: layers[name]["order"])
            except (KeyError, TypeError) as error:
                raise ValueError("layers.yaml source layers require an order") from error
        else:
            names = [name for name in selection.split(",") if name]
        if not names:
            raise ValueError("no layers selected")
        result: list[tuple[str, tuple[str, ...]]] = []
        for name in names:
            layer = layers.get(name)
            if not isinstance(layer, dict):
                raise ValueError(f"unknown layer: {name}")
            filters = layer.get("tags_filter")
            if (
                not isinstance(filters, list)
                or not filters
                or any(not isinstance(value, str) or not value for value in filters)
            ):
                raise ValueError(f"layer has no tags_filter: {name}")
            result.append((name, tuple(filters)))
        return tuple(result)

    def export_layers(self, selection: str) -> tuple[tuple[str, bool], ...]:
        selected = self.tags_filter_layers(selection)
        layers = self._repository.load("layers")["source_layers"]
        return tuple(
            (name, layers[name].get("export_keep_untagged", False) is True)
            for name, _filters in selected
        )

    def normalization_layers(
        self, selection: str
    ) -> tuple[tuple[str, tuple[str, ...], dict[str, Any]], ...]:
        selected = self.tags_filter_layers(selection)
        layers = self._repository.load("layers")["source_layers"]
        result = []
        for name, _filters in selected:
            layer = layers[name]
            fields = layer.get("final_fields")
            post_filter = layer.get("post_filter", {})
            if not isinstance(fields, dict) or not isinstance(post_filter, dict):
                raise ValueError(f"layer has invalid normalization policy: {name}")
            allowed = tuple(fields)
            if name == "place_label" and "@id" not in allowed:
                allowed = tuple(sorted((*allowed, "@id")))
            result.append((name, allowed, post_filter))
        return tuple(result)

    def final_layer_contracts(
        self, selection: str
    ) -> tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...]:
        selected = self.tags_filter_layers(selection)
        layers = self._repository.load("layers")["source_layers"]
        contracts = []
        for name, _filters in selected:
            layer = layers[name]
            fields = layer.get("final_fields")
            geometry = layer.get("post_filter", {}).get("geometry", [])
            if (
                not isinstance(fields, dict)
                or not isinstance(geometry, list)
                or any(not isinstance(value, str) for value in geometry)
            ):
                raise ValueError(f"layer has invalid final contract: {name}")
            contracts.append((name, tuple(fields), tuple(geometry)))
        return tuple(contracts)

    def final_field_types(self, selection: str) -> dict[str, dict[str, str]]:
        selected = self.tags_filter_layers(selection)
        layers = self._repository.load("layers")["source_layers"]
        result = {}
        for name, _filters in selected:
            fields = layers[name].get("final_fields")
            if not isinstance(fields, dict) or any(
                not isinstance(field, str)
                or not isinstance(field_type, str)
                or field_type not in {"String", "Number", "Boolean"}
                for field, field_type in fields.items()
            ):
                raise ValueError(f"layer has invalid final field types: {name}")
            result[name] = dict(fields)
        return result

    def layer_export_findings(self) -> tuple[ConfigurationFinding, ...]:
        layers = self._repository.load("layers")
        definitions = layers.get("source_layers", {})
        if not isinstance(definitions, dict):
            definitions = {}
        exports = {}
        for name in definitions:
            try:
                exports[name] = self._repository.load_export(name)
            except RuntimeError:
                continue
        return inspect_layer_export_contracts(layers, exports)

    def default_name_locale_priority(self) -> tuple[str, ...]:
        value = self._repository.load("layers").get("global", {}).get(
            "name_coalesce_order"
        )
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ValueError("layers.yaml has invalid global.name_coalesce_order")
        return tuple(value)

    def profile_transform(self, region: str) -> dict[str, Any] | None:
        tiers = self._repository.load("tier-profiles")
        entry = tiers.get("regions", {}).get(region)
        if not isinstance(entry, dict) or not entry.get("build_profile"):
            return None
        name = entry["build_profile"]
        profile = tiers.get("profiles", {}).get(name)
        if not isinstance(profile, dict):
            raise ValueError(f"unknown tier profile: {name}")
        settings = self.tippecanoe(region, "base")
        vector_layers = self.vector_layers(region, "base", settings["max_zoom"])
        feature_rules = profile.get("feature_rules", {})
        return {
            "name": name,
            "layers": [
                {
                    "name": layer["id"],
                    "min_zoom": layer["minzoom"],
                    "max_zoom": layer["maxzoom"],
                    "rules": feature_rules.get(layer["id"]),
                }
                for layer in vector_layers
            ],
        }

    def admin_line_hierarchy(
        self, region: str = "", default_only: bool = False
    ) -> dict[str, dict[str, Any]]:
        document = self._repository.load("admin-line-hierarchy")
        tier_zoom = document.get("tier_zoom")
        default = document.get("default")
        profiles = document.get("profiles", [])
        if (
            document.get("schema_version") != 1
            or not isinstance(tier_zoom, dict) or not tier_zoom
            or not isinstance(default, dict)
            or not isinstance(default.get("level_tier"), dict)
            or not default["level_tier"]
            or not isinstance(profiles, list)
        ):
            raise ValueError("invalid admin-line hierarchy configuration")
        for name, zoom in tier_zoom.items():
            if (
                not isinstance(name, str)
                or not isinstance(zoom, dict)
                or not self._valid_zoom(zoom)
            ):
                raise ValueError("invalid admin-line hierarchy configuration")
        mappings = [default, *profiles]
        for mapping in mappings:
            levels = mapping.get("level_tier") if isinstance(mapping, dict) else None
            if not isinstance(levels, dict) or not levels:
                raise ValueError("invalid admin-line hierarchy configuration")
            if any(
                not isinstance(level, str) or not level.isdigit()
                or not isinstance(tier, str) or tier not in tier_zoom
                for level, tier in levels.items()
            ):
                raise ValueError("invalid admin-line hierarchy configuration")
        selected = default
        if not default_only:
            for profile in profiles:
                regions = profile.get("regions")
                if not isinstance(regions, list) or not regions or any(
                    not isinstance(prefix, str) or not prefix for prefix in regions
                ):
                    raise ValueError("invalid admin-line hierarchy configuration")
                if any(region == prefix or region.startswith(f"{prefix}/") for prefix in regions):
                    selected = profile
                    break
        return {
            "level_tier": dict(selected["level_tier"]),
            "tier_zoom": {name: dict(zoom) for name, zoom in tier_zoom.items()},
        }

    def require_overview(self, overview: str) -> None:
        if not overview or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789-"
            for character in overview
        ):
            raise ValueError(f"invalid overview id: {overview}")
        document = self._repository.load("overviews")
        overviews = document.get("overviews")
        if not isinstance(overviews, list) or not any(
            isinstance(item, dict) and item.get("id") == overview for item in overviews
        ):
            raise ValueError(f"overview is not configured: {overview}")

    def place_label_hierarchy(self, region: str) -> dict[str, Any]:
        document = self._repository.load("place-label-hierarchy")
        required_objects = (
            "boundary_tier", "tier_expected_place", "place_fallback_tier",
            "rank", "tier_zoom",
        )
        if document.get("schema_version") != 1 or any(
            not isinstance(document.get(key), dict) or not document[key]
            for key in required_objects
        ):
            raise ValueError("invalid place-label hierarchy configuration")
        boundary = document["boundary_tier"]
        expected = document["tier_expected_place"]
        fallback = document["place_fallback_tier"]
        ranks = document["rank"]
        zooms = document["tier_zoom"]
        if "default" not in fallback or "default" not in zooms:
            raise ValueError("invalid place-label hierarchy configuration")
        tiers = tuple(boundary.values()) + tuple(fallback.values())
        if (
            any(not isinstance(level, str) or not level.isdigit()
                or not isinstance(tier, str) or not tier for level, tier in boundary.items())
            or any(not isinstance(values, list)
                   or any(not isinstance(value, str) for value in values)
                   for values in expected.values())
            or any(not isinstance(tier, str) or not tier for tier in fallback.values())
            or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                   or value < 0 for value in ranks.values())
            or any(tier not in ranks or tier not in zooms for tier in tiers)
            or any(not isinstance(zoom, dict) or not self._valid_place_zoom(zoom)
                   for zoom in zooms.values())
        ):
            raise ValueError("invalid place-label hierarchy configuration")
        dedupe = document.get("dedupe_name_tiers", [])
        if not isinstance(dedupe, list) or any(
            not isinstance(tier, str) or tier not in zooms for tier in dedupe
        ):
            raise ValueError("invalid place-label hierarchy configuration")
        display = self._place_admin_display_name(document, region, ranks)
        conventional = self._conventional_region_filter(document, ranks, zooms)
        return {
            "boundary_tier": dict(boundary),
            "tier_expected_place": {key: list(value) for key, value in expected.items()},
            "place_fallback_tier": dict(fallback),
            "rank": dict(ranks),
            "tier_zoom": {key: dict(value) for key, value in zooms.items()},
            "dedupe_name_tiers": list(dedupe),
            "admin_display_name": display,
            "conventional_region_filter": conventional,
        }

    @staticmethod
    def _conventional_region_filter(
        document: dict[str, Any], ranks: dict[str, Any], zooms: dict[str, Any]
    ) -> dict[str, Any]:
        policy = document.get("conventional_region_filter")
        if not isinstance(policy, dict):
            raise ValueError("invalid place-label hierarchy configuration")
        enabled = policy.get("enabled")
        action = policy.get("action")
        places = policy.get("places")
        tiers = policy.get("tiers")
        levels = policy.get("admin_evidence_levels")
        prefix = policy.get("min_prefix_len")
        population_evidence = policy.get("population_is_admin_evidence")
        maximum = policy.get("max_candidates")
        keep_names = policy.get("keep_names")
        if (
            not isinstance(enabled, bool)
            or action not in {"drop", "demote", "report_only"}
            or not isinstance(places, list) or not places
            or any(not isinstance(value, str) or not value for value in places)
            or not isinstance(tiers, list) or not tiers
            or any(not isinstance(value, str) or value not in ranks or value not in zooms
                   for value in tiers)
            or not isinstance(levels, list) or not levels
            or any(not isinstance(value, int) or isinstance(value, bool) or value <= 0
                   for value in levels)
            or len(set(levels)) != len(levels)
            or not isinstance(prefix, int) or isinstance(prefix, bool)
            or not 2 <= prefix <= 8
            or not isinstance(population_evidence, bool)
            or not isinstance(maximum, int) or isinstance(maximum, bool) or maximum <= 0
            or not isinstance(keep_names, list)
            or any(not isinstance(value, str) or not value.strip() for value in keep_names)
        ):
            raise ValueError("invalid place-label hierarchy configuration")
        return {
            "enabled": enabled,
            "action": action,
            "places": list(places),
            "tiers": list(tiers),
            "admin_evidence_levels": list(levels),
            "min_prefix_len": prefix,
            "population_is_admin_evidence": population_evidence,
            "max_candidates": maximum,
            "keep_names": list(keep_names),
        }

    def style(self, region: str, locale: str | None = None) -> dict[str, Any]:
        document = self._repository.load("styles")
        locales = document.get("locales")
        text_layers = document.get("text_layers")
        paint_layers = document.get("paint_layers", [])
        if (
            document.get("schema_version") != 1
            or not isinstance(locales, list) or not locales
            or not isinstance(text_layers, list)
            or not isinstance(paint_layers, list)
        ):
            raise ValueError("invalid styles configuration")
        tags = [entry.get("tag") for entry in locales if isinstance(entry, dict)]
        selected = locale or tags[0]
        if selected not in tags:
            raise ValueError(f"style locale is not configured: {selected}")
        locale_config = locales[tags.index(selected)]
        names = locale_config.get("name_fields")
        fonts = locale_config.get("font_stack")
        if (
            not isinstance(names, list) or not names
            or any(not isinstance(value, str) or not value for value in names)
            or not isinstance(fonts, list) or not fonts
            or any(not isinstance(value, str) or not value for value in fonts)
        ):
            raise ValueError("invalid styles configuration")
        for layer in (*text_layers, *paint_layers):
            if not isinstance(layer, dict) or not isinstance(layer.get("id"), str):
                raise ValueError("invalid styles configuration")
            if not isinstance(layer.get("source_layer"), str):
                raise ValueError("invalid styles configuration")
        settings = self.tippecanoe(region, "base")
        return {
            "config": document,
            "locale": selected,
            "effective_base_layers": list(settings["source_layers"]),
        }

    def sprite_manifest(self) -> dict[str, Any]:
        document = self._repository.load("icons/manifest")
        sprite = document.get("sprite")
        icons = document.get("icons")
        if (
            document.get("schema_version") != 1
            or not isinstance(sprite, dict)
            or not isinstance(icons, list) or not icons
        ):
            raise ValueError("invalid icon manifest")
        for field in ("icon_size", "padding"):
            value = sprite.get(field)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("invalid icon manifest")
        if sprite["icon_size"] <= 0:
            raise ValueError("invalid icon manifest")
        seen: set[str] = set()
        allowed_shapes = {
            "triangle", "rail", "station", "metro", "tram", "bus", "museum",
            "star", "tree", "viewpoint", "bed", "cross", "school",
            "service-area", "parking", "circle",
        }
        for icon in icons:
            if not isinstance(icon, dict):
                raise ValueError("invalid icon manifest")
            icon_id, shape, color = icon.get("id"), icon.get("shape", "circle"), icon.get("color", "#4b5563")
            if (
                not isinstance(icon_id, str) or not icon_id or icon_id in seen
                or shape not in allowed_shapes
                or not isinstance(color, str) or len(color) != 7 or not color.startswith("#")
            ):
                raise ValueError("invalid icon manifest")
            try:
                int(color[1:], 16)
            except ValueError as error:
                raise ValueError("invalid icon manifest") from error
            seen.add(icon_id)
        return document

    def glyph_manifest(self) -> dict[str, Any]:
        document = self._repository.load("glyphs")
        generator = document.get("generator")
        fonts = document.get("fonts")
        ranges = document.get("ranges")
        locales = document.get("locales")
        if (
            document.get("schema_version") != 1
            or not isinstance(generator, dict)
            or not isinstance(generator.get("command"), str)
            or not generator["command"]
            or not isinstance(generator.get("url_template"), str)
            or "{locale}" not in generator["url_template"]
            or "{fontstack}" not in generator["url_template"]
            or "{range}.pbf" not in generator["url_template"]
            or not isinstance(fonts, list) or not fonts
            or not isinstance(ranges, list) or not ranges
            or not isinstance(locales, list) or not locales
        ):
            raise ValueError("invalid glyph configuration")
        font_ids: set[str] = set()
        fontstacks: set[str] = set()
        for font in fonts:
            if not isinstance(font, dict):
                raise ValueError("invalid glyph configuration")
            font_id, fontstack, file = (
                font.get("id"), font.get("fontstack"), font.get("file")
            )
            if (
                not isinstance(font_id, str) or not font_id or font_id in font_ids
                or not isinstance(fontstack, str) or not fontstack
                or fontstack in fontstacks
                or not isinstance(file, str) or not file
            ):
                raise ValueError("invalid glyph configuration")
            font_ids.add(font_id)
            fontstacks.add(fontstack)
        previous_end = -1
        for item in ranges:
            if not isinstance(item, dict):
                raise ValueError("invalid glyph configuration")
            start, end = item.get("start"), item.get("end")
            if (
                not isinstance(start, int) or isinstance(start, bool)
                or not isinstance(end, int) or isinstance(end, bool)
                or start < 0 or end < start or start <= previous_end
            ):
                raise ValueError("invalid glyph configuration")
            previous_end = end
        locale_tags: set[str] = set()
        for locale in locales:
            if not isinstance(locale, dict):
                raise ValueError("invalid glyph configuration")
            tag, selected_fonts = locale.get("tag"), locale.get("fonts")
            if (
                not isinstance(tag, str) or not tag or tag in locale_tags
                or not isinstance(selected_fonts, list) or not selected_fonts
                or any(font not in font_ids for font in selected_fonts)
            ):
                raise ValueError("invalid glyph configuration")
            locale_tags.add(tag)
        return document

    @staticmethod
    def _valid_place_zoom(zoom: dict[str, Any]) -> bool:
        minimum, maximum = zoom.get("minzoom"), zoom.get("maxzoom")
        return (
            isinstance(minimum, (int, float)) and not isinstance(minimum, bool)
            and minimum >= 0
            and (maximum is None or (
                isinstance(maximum, (int, float)) and not isinstance(maximum, bool)
                and maximum > minimum
            ))
        )

    @staticmethod
    def _place_admin_display_name(
        document: dict[str, Any], region: str, ranks: dict[str, Any]
    ) -> dict[str, Any]:
        root = document.get("admin_display_name", {})
        if not isinstance(root, dict) or not isinstance(root.get("default"), dict):
            raise ValueError("invalid place-label hierarchy configuration")
        profiles = root.get("profiles", [])
        if not isinstance(profiles, list):
            raise ValueError("invalid place-label hierarchy configuration")
        candidates = [root["default"], *profiles]
        for profile in candidates:
            if not isinstance(profile, dict):
                raise ValueError("invalid place-label hierarchy configuration")
            for key in ("tiers", "locality_keywords", "target_fields"):
                values = profile.get(key)
                if (not isinstance(values, list) or not values
                    or any(not isinstance(value, str) or not value for value in values)):
                    if key == "locality_keywords" and values == []:
                        continue
                    raise ValueError("invalid place-label hierarchy configuration")
            if any(tier not in ranks for tier in profile["tiers"]):
                raise ValueError("invalid place-label hierarchy configuration")
            if profile is not root["default"]:
                prefixes = profile.get("regions")
                if (not isinstance(prefixes, list) or not prefixes
                    or any(not isinstance(value, str) or not value for value in prefixes)):
                    raise ValueError("invalid place-label hierarchy configuration")
        selected = root["default"]
        for profile in profiles:
            if any(region == prefix or region.startswith(f"{prefix}/")
                   for prefix in profile["regions"]):
                selected = profile
                break
        result = dict(selected)
        result["enabled"] = selected.get("enabled", True)
        return result

    @staticmethod
    def _valid_zoom(value: dict[str, Any]) -> bool:
        minimum, maximum = value.get("minzoom"), value.get("maxzoom")
        return (
            isinstance(minimum, int) and not isinstance(minimum, bool) and minimum >= 0
            and isinstance(maximum, int) and not isinstance(maximum, bool)
            and minimum <= maximum <= 15
        )

    def validate(self) -> ConfigurationSummary:
        documents = {
            name: self._repository.load(name)
            for name in ("layers", "tippecanoe", "tier-profiles", "bake")
        }
        versions: list[tuple[str, str]] = []
        for name, document in documents.items():
            version = document.get("schema_version")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise ValueError(f"{name}.yaml has invalid schema_version")
            versions.append((name, str(version)))

        layers = documents["layers"].get("source_layers")
        if not isinstance(layers, dict) or not layers:
            raise ValueError("layers.yaml source_layers must be a non-empty object")
        profiles = documents["tier-profiles"].get("profiles")
        regions = documents["tier-profiles"].get("regions")
        if not isinstance(profiles, dict) or not isinstance(regions, dict):
            raise ValueError("tier-profiles.yaml profiles and regions must be objects")

        for region, entry in regions.items():
            if not isinstance(entry, dict):
                raise ValueError(f"tier profile region {region} must be an object")
            resolved = resolve_tippecanoe(documents["tippecanoe"], region, "base")
            resolved = apply_tier_profile(
                resolved,
                documents["tier-profiles"],
                documents["layers"],
                region,
                "base",
            )
            resolve_vector_layers(
                resolved,
                documents["tier-profiles"],
                documents["layers"],
                region,
                "base",
                resolved["max_zoom"],
            )

        for role in ("base", "building"):
            resolved = resolve_tippecanoe(documents["tippecanoe"], "__validation__", role)
            resolve_vector_layers(
                resolved,
                documents["tier-profiles"],
                documents["layers"],
                "__validation__",
                role,
                resolved["max_zoom"],
            )
        bake = resolve_raster_bake(documents["bake"], "__validation__")
        for override in [{}, *documents["bake"].get("high_density", [])]:
            effective = {**bake, **override}
            if effective.get("renderer_engine", "maplibre-native-headless") not in (
                "mbgl-renderer", "maplibre-native", "maplibre-native-headless",
            ):
                raise ValueError("bake.yaml has invalid renderer_engine")
            jobs = effective.get("native_parallel_jobs", 1)
            if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs <= 0:
                raise ValueError("bake.yaml native_parallel_jobs must be a positive integer")
        for key in ("tile_size", "min_zoom", "max_zoom", "parallel_jobs"):
            if not isinstance(bake.get(key), int) or isinstance(bake.get(key), bool):
                raise ValueError(f"bake.yaml raster_bake.{key} must be an integer")
        if bake["tile_size"] <= 0 or bake["parallel_jobs"] <= 0:
            raise ValueError("bake.yaml tile_size and parallel_jobs must be positive")
        if bake["min_zoom"] < 0 or bake["max_zoom"] < bake["min_zoom"]:
            raise ValueError("bake.yaml has invalid zoom range")

        return ConfigurationSummary(
            layer_count=len(layers),
            tier_profile_count=len(profiles),
            schema_versions=tuple(versions),
        )

    def vector_layers(
        self, region: str, role: str, tile_max: int | None = None
    ) -> list[dict[str, Any]]:
        tippecanoe = self.tippecanoe(region, role)
        resolved_tile_max = tile_max if tile_max is not None else tippecanoe["max_zoom"]
        return resolve_vector_layers(
            tippecanoe,
            self._repository.load("tier-profiles"),
            self._repository.load("layers"),
            region,
            role,
            resolved_tile_max,
        )

    def tier_profile_schema_version(self) -> int:
        value = self._repository.load("tier-profiles").get("schema_version")
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ValueError("tier-profiles.yaml has invalid schema_version")
        return value
