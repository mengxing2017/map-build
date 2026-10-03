from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any


class BuildConfigurationError(ValueError):
    """Raised when a build configuration document violates its contract."""


@dataclass(frozen=True, slots=True)
class ConfigurationFinding:
    code: str
    layer: str
    detail: str


def inspect_layer_export_contracts(
    document: dict[str, Any], exports: dict[str, dict[str, Any]]
) -> tuple[ConfigurationFinding, ...]:
    findings: list[ConfigurationFinding] = []
    layers = document.get("source_layers")
    if not isinstance(layers, dict):
        return (ConfigurationFinding(
            "config-layers", "layers", "source_layers must be an object"
        ),)

    expected_locale_order = ("name:zh-Hans", "name:zh", "name", "name:en")
    actual_locale_order = document.get("global", {}).get("name_coalesce_order")
    if tuple(actual_locale_order or ()) != expected_locale_order:
        findings.append(ConfigurationFinding(
            "config-locale", "global",
            "name_coalesce_order must be name:zh-Hans,name:zh,name,name:en",
        ))

    for name, layer in layers.items():
        if not isinstance(layer, dict):
            findings.append(ConfigurationFinding(
                "config-layer", str(name), "layer definition must be an object"
            ))
            continue
        include = layer.get("include_tags", [])
        final = layer.get("final_fields", {})
        normalize = layer.get("normalize", {})
        enrich = layer.get("enrich_fields", [])
        if not isinstance(include, list) or not isinstance(final, dict):
            findings.append(ConfigurationFinding(
                "config-fields", name, "include_tags/final_fields have invalid types"
            ))
            continue
        declared = set(include)
        if isinstance(normalize, dict):
            declared.update(normalize)
        if isinstance(enrich, list):
            declared.update(enrich)
        for field in sorted(set(final) - declared):
            findings.append(ConfigurationFinding(
                "config-final-field", name,
                f"final field is not declared by include_tags, normalize, or enrichment: {field}",
            ))

        export = exports.get(name)
        if not isinstance(export, dict):
            findings.append(ConfigurationFinding(
                "export-config-missing", name, "export configuration is missing"
            ))
        else:
            exported = export.get("include_tags", [])
            if not isinstance(exported, list) or set(exported) != set(include):
                findings.append(ConfigurationFinding(
                    "export-config-tags", name,
                    "export include_tags do not match layers.yaml",
                ))

    required_fields = {
        "road": ("ref", "highway"),
        "railway": ("railway", "highspeed"),
        "water": ("water", "intermittent", "place"),
        "waterway": ("waterway", "width"),
        "landuse": ("landuse",),
        "natural_a": ("natural",),
        "natural_line": ("natural",),
        "leisure_a": ("leisure",),
        "building": ("building",),
        "island": ("place",),
        "peak": ("natural", "ele"),
        "highway_point": ("highway", "ref", "network"),
        "transport_label": ("public_transport", "railway", "ref", "network"),
        "poi_label": ("amenity", "shop", "tourism"),
    }
    locale_layers = (
        "road", "railway", "water", "waterway", "landuse", "building", "admin",
        "natural_a", "natural_line", "peak", "leisure_a", "place_label",
        "poi_label", "transport_label", "highway_point", "island",
    )
    for name in locale_layers:
        _require_fields(findings, layers, exports, name, ("name:zh",))
    for name, fields in required_fields.items():
        _require_fields(findings, layers, exports, name, fields)
    _require_final_fields(
        findings, layers, "place_label",
        ("admin_id", "boundary_admin_level", "label_tier", "label_rank"),
    )
    _require_filters(
        findings, layers, "poi_label",
        ("a/amenity=hospital", "a/amenity=school", "w/tourism", "a/tourism"),
    )

    area_contracts = {
        "water": ("natural=water", ("Polygon", "MultiPolygon")),
        "building": ("building", ("Polygon", "MultiPolygon")),
        "landuse": ("landuse", ("Polygon", "MultiPolygon")),
        "natural_a": ("natural", ("Polygon", "MultiPolygon")),
        "leisure_a": ("leisure", ("Polygon", "MultiPolygon")),
        "island": ("place", ("Polygon", "MultiPolygon", "Point")),
    }
    for name, (area_tag, geometry) in area_contracts.items():
        export = exports.get(name, {})
        layer = layers.get(name, {})
        if export.get("area_tags") != [area_tag]:
            findings.append(ConfigurationFinding(
                "export-config-area", name, f"area_tags must equal [{area_tag}]"
            ))
        if layer.get("post_filter", {}).get("geometry") != list(geometry):
            findings.append(ConfigurationFinding(
                "config-geometry", name,
                f"post_filter.geometry must equal {','.join(geometry)}",
            ))

    for name, linear_tags in {
        "poi_label": ["amenity", "tourism"],
        "highway_point": ["highway=services", "highway=rest_area"],
    }.items():
        export = exports.get(name, {})
        attributes = export.get("attributes", {})
        if (
            attributes.get("type") is not False
            or attributes.get("id") is not False
            or export.get("area_tags", [])
            or export.get("linear_tags") != linear_tags
        ):
            findings.append(ConfigurationFinding(
                "export-config-linear", name,
                "point label export type/id, area_tags, or linear_tags contract is invalid",
            ))
    return tuple(findings)


def _require_fields(
    findings: list[ConfigurationFinding], layers: dict[str, Any],
    exports: dict[str, dict[str, Any]], name: str, fields: tuple[str, ...],
) -> None:
    layer = layers.get(name, {})
    include = layer.get("include_tags", [])
    final = layer.get("final_fields", {})
    exported = exports.get(name, {}).get("include_tags", [])
    for field in fields:
        if field not in include or field not in final or field not in exported:
            findings.append(ConfigurationFinding(
                "config-required-field", name,
                f"field must exist in include_tags, final_fields, and export config: {field}",
            ))


def _require_final_fields(
    findings: list[ConfigurationFinding], layers: dict[str, Any],
    name: str, fields: tuple[str, ...],
) -> None:
    final = layers.get(name, {}).get("final_fields", {})
    for field in fields:
        if field not in final:
            findings.append(ConfigurationFinding(
                "config-required-field", name,
                f"field must exist in final_fields: {field}",
            ))


def _require_filters(
    findings: list[ConfigurationFinding], layers: dict[str, Any],
    name: str, filters: tuple[str, ...],
) -> None:
    actual = layers.get(name, {}).get("tags_filter", [])
    for value in filters:
        if value not in actual:
            findings.append(ConfigurationFinding(
                "config-tags-filter", name, f"required tags_filter is missing: {value}"
            ))


def resolve_tippecanoe(
    document: dict[str, Any], region: str, role: str
) -> dict[str, Any]:
    defaults = _object(document, "defaults")
    resolved = deepcopy(defaults)
    baseline = defaults.get("high_density_baseline")
    if baseline is not None:
        if not isinstance(baseline, dict):
            raise BuildConfigurationError("high_density_baseline must be an object")
        resolved.update(deepcopy(baseline))

    if role == "building":
        building = _object(document, "building_vector")
        for key in (
            "min_zoom",
            "max_zoom",
            "maximum_tile_bytes",
            "output_role",
            "source_layers",
        ):
            resolved[key] = deepcopy(building[key])

    for override in _array(document, "high_density"):
        pattern = str(override.get("region_match", ""))
        if _shell_pattern_matches(region, pattern):
            resolved.update(
                deepcopy(
                    {
                        key: value
                        for key, value in override.items()
                        if key not in {"region_match", "building_height_derivation"}
                    }
                )
            )
    return resolved


def resolve_raster_bake(document: dict[str, Any], region: str) -> dict[str, Any]:
    defaults = _object(_object(document, "defaults"), "raster_bake")
    resolved = deepcopy(defaults)
    for override in _array(document, "high_density"):
        pattern = str(override.get("region_match", ""))
        if _shell_pattern_matches(region, pattern):
            resolved.update(
                deepcopy({key: value for key, value in override.items() if key != "region_match"})
            )
    return resolved


def apply_tier_profile(
    resolved: dict[str, Any],
    tier_document: dict[str, Any],
    layers_document: dict[str, Any],
    region: str,
    role: str,
) -> dict[str, Any]:
    if role != "base":
        return resolved
    region_profiles = _object(tier_document, "regions")
    region_entry = region_profiles.get(region)
    if region_entry is None:
        return resolved
    if not isinstance(region_entry, dict):
        raise BuildConfigurationError(f"tier profile region {region} must be an object")
    profile_name = region_entry.get("build_profile")
    if not isinstance(profile_name, str) or not profile_name:
        return resolved
    profiles = _object(tier_document, "profiles")
    profile = profiles.get(profile_name)
    if not isinstance(profile, dict):
        raise BuildConfigurationError(f"unknown tier profile: {profile_name}")
    _validate_tier_profile(profile_name, profile, layers_document)

    result = deepcopy(resolved)
    for key in (
        "min_zoom",
        "max_zoom",
        "maximum_tile_bytes",
        "extend_zooms_if_still_dropping",
        "source_layers",
    ):
        result[key] = deepcopy(profile[key])
    result.update(deepcopy(profile.get("tippecanoe", {})))
    return result


def resolve_vector_layers(
    tippecanoe: dict[str, Any],
    tier_document: dict[str, Any],
    layers_document: dict[str, Any],
    region: str,
    role: str,
    tile_max: int,
) -> list[dict[str, Any]]:
    if not isinstance(tile_max, int) or isinstance(tile_max, bool) or tile_max < 0:
        raise BuildConfigurationError(f"invalid tile max zoom: {tile_max}")
    source_layers = tippecanoe.get("source_layers")
    if not isinstance(source_layers, list):
        raise BuildConfigurationError("Tippecanoe source_layers must be an array")
    known_layers = _object(layers_document, "source_layers")
    profile = _tier_profile(tier_document, region, role)
    feature_rules = profile.get("feature_rules", {}) if profile else {}

    result: list[dict[str, Any]] = []
    for layer in source_layers:
        definition = known_layers.get(layer)
        if not isinstance(definition, dict):
            raise BuildConfigurationError(f"unknown source layer: {layer}")
        fields = definition.get("final_fields", {})
        if not isinstance(fields, dict):
            raise BuildConfigurationError(f"layer {layer} final_fields must be an object")
        rules = feature_rules.get(layer, {}).get("rules", [])
        if rules:
            min_zoom = min(rule["min_zoom"] for rule in rules)
            max_zoom = max(rule["max_zoom"] for rule in rules)
        else:
            min_zoom = _layer_min_zoom(layer)
            max_zoom = _layer_max_zoom(layer, role, tile_max)
        result.append(
            {
                "id": layer,
                "minzoom": min_zoom,
                "maxzoom": min(max_zoom, tile_max),
                "fields": deepcopy(fields),
            }
        )
    return result


def _shell_pattern_matches(value: str, pattern: str) -> bool:
    return fnmatchcase(value, pattern.replace("**", "*"))


def _validate_tier_profile(
    name: str, profile: dict[str, Any], layers_document: dict[str, Any]
) -> None:
    min_zoom = profile.get("min_zoom")
    max_zoom = profile.get("max_zoom")
    maximum_tile_bytes = profile.get("maximum_tile_bytes")
    source_layers = profile.get("source_layers")
    if (
        not isinstance(min_zoom, int)
        or isinstance(min_zoom, bool)
        or min_zoom < 0
        or not isinstance(max_zoom, int)
        or isinstance(max_zoom, bool)
        or max_zoom < min_zoom
        or max_zoom > 15
        or not isinstance(maximum_tile_bytes, int)
        or isinstance(maximum_tile_bytes, bool)
        or maximum_tile_bytes <= 0
        or profile.get("extend_zooms_if_still_dropping") is not False
        or not isinstance(source_layers, list)
        or not source_layers
        or len(source_layers) != len(set(source_layers))
    ):
        raise BuildConfigurationError(f"invalid tier profile: {name}")

    known_layers = _object(layers_document, "source_layers")
    for layer in source_layers:
        if layer not in known_layers:
            raise BuildConfigurationError(
                f"tier profile {name} references unknown layer: {layer}"
            )
    feature_rules = profile.get("feature_rules", {})
    if not isinstance(feature_rules, dict):
        raise BuildConfigurationError(f"tier profile {name} has invalid feature rules")
    for layer, rule_set in feature_rules.items():
        if layer not in source_layers or not isinstance(rule_set, dict):
            raise BuildConfigurationError(
                f"tier profile {name} has rules for disabled layer: {layer}"
            )
        final_fields = known_layers[layer].get("final_fields", {})
        rules = rule_set.get("rules")
        if rule_set.get("default") != "exclude" or not isinstance(rules, list) or not rules:
            raise BuildConfigurationError(f"tier profile {name} has invalid feature rules")
        for rule in rules:
            when = rule.get("when") if isinstance(rule, dict) else None
            rule_min = rule.get("min_zoom") if isinstance(rule, dict) else None
            rule_max = rule.get("max_zoom") if isinstance(rule, dict) else None
            if (
                not isinstance(when, dict)
                or not when
                or not isinstance(rule_min, int)
                or not isinstance(rule_max, int)
                or rule_min < min_zoom
                or rule_max < rule_min
                or rule_max > max_zoom
            ):
                raise BuildConfigurationError(
                    f"tier profile {name} has invalid feature rules"
                )
            unknown_fields = set(when) - set(final_fields)
            if unknown_fields:
                field = sorted(unknown_fields)[0]
                raise BuildConfigurationError(
                    f"tier profile {name} rule references unknown final field: {layer}.{field}"
                )


def _tier_profile(
    document: dict[str, Any], region: str, role: str
) -> dict[str, Any] | None:
    if role != "base":
        return None
    region_entry = _object(document, "regions").get(region)
    if not isinstance(region_entry, dict):
        return None
    name = region_entry.get("build_profile")
    if not isinstance(name, str) or not name:
        return None
    profile = _object(document, "profiles").get(name)
    if not isinstance(profile, dict):
        raise BuildConfigurationError(f"unknown tier profile: {name}")
    return profile


def _layer_min_zoom(layer: str) -> int:
    return {
        "building": 12,
        "natural_line": 10,
        "peak": 10,
        "leisure_a": 10,
        "place_label": 2,
        "poi_label": 14,
        "transport_label": 13,
        "highway_point": 10,
    }.get(layer, 0)


def _layer_max_zoom(layer: str, role: str, tile_max: int) -> int:
    if role == "building" and layer == "building":
        return tile_max
    default = {
        "road": 15,
        "building": 15,
        "natural_line": 15,
        "poi_label": 15,
        "transport_label": 15,
        "peak": 15,
        "highway_point": 15,
        "admin": 8,
    }.get(layer, 14)
    return min(default, tile_max)


def _object(document: dict[str, Any], key: str) -> dict[str, Any]:
    value = document.get(key)
    if not isinstance(value, dict):
        raise BuildConfigurationError(f"{key} must be an object")
    return value


def _array(document: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = document.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise BuildConfigurationError(f"{key} must be an array of objects")
    return value
