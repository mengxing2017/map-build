from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


@dataclass(frozen=True, slots=True)
class StyleDocuments:
    vector: dict[str, Any]
    bake: dict[str, Any]
    raster: dict[str, Any]


@dataclass(frozen=True, slots=True)
class StyleRequest:
    region: RegionId
    session: SessionId
    workdir: str
    locale: str | None = None
    pmtiles_url: str | None = None


def default_zoom(bounds: tuple[float, float, float, float]) -> int:
    from math import asin, cos, radians, sin, sqrt

    west, south, east, north = map(radians, bounds)
    latitude, longitude = north - south, east - west
    value = sin(latitude / 2) ** 2 + cos(south) * cos(north) * sin(longitude / 2) ** 2
    diagonal = 2 * 6371.0 * asin(sqrt(value))
    for distance, zoom in ((800, 4), (400, 5), (150, 6), (80, 7),
                           (30, 8), (10, 9), (4, 10)):
        if diagonal > distance:
            return zoom
    return 11


def compile_styles(
    config: dict[str, Any], locale: str, effective_layers: list[str],
    viewport: dict[str, Any] | None = None, pmtiles_url: str | None = None,
) -> StyleDocuments:
    locale_config = next(
        (entry for entry in config["locales"] if entry.get("tag") == locale), None
    )
    if locale_config is None:
        raise ValueError(f"style locale is not configured: {locale}")
    source = config.get("source", {})
    source_id = source.get("id", "huavd-offline")
    source_type = source.get("type", "vector")
    source_url = pmtiles_url or source.get("url", "pmtiles://{pmtiles}")
    glyphs_template = config.get(
        "glyphs_url", "huavd-map://glyphs/{locale}/{fontstack}/{range}.pbf"
    )
    glyphs_url = glyphs_template.replace("{locale}", locale)
    sprite_url = config.get("sprite", "huavd-map://sprite/sprite")
    enabled = set(effective_layers)
    paint_layers = [
        _compile_paint_layer(layer, source_id)
        for layer in config.get("paint_layers", [])
        if layer["source_layer"] in enabled
    ]
    text_layers = [
        _compile_text_layer(layer, source_id, locale, locale_config)
        for layer in config.get("text_layers", [])
        if layer["source_layer"] in enabled
    ]
    vector: dict[str, Any] = {
        "version": 8,
        "name": "HUAVD offline vector style",
        "glyphs": glyphs_url,
        "sources": {source_id: {"type": source_type, "url": source_url}},
        "layers": (
            [{"id": "background", "type": "background",
              "paint": {"background-color": "#f4f2ed"}}]
            + [layer for layer in paint_layers if layer["type"] != "symbol"]
            + [layer for layer in paint_layers if layer["type"] == "symbol"]
            + text_layers
        ),
        "metadata": {
            "huavd:style-locale": locale,
            "huavd:viewport": viewport or {},
        },
    }
    if viewport:
        for key in ("min_zoom", "max_zoom"):
            value = viewport.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                vector["sources"][source_id][key.replace("_", "")] = value
    if sprite_url not in (None, "", "null"):
        vector["sprite"] = sprite_url
    return StyleDocuments(vector, _compile_bake(vector, config), _compile_raster(vector, config))


def _compile_paint_layer(layer: dict[str, Any], source_id: str) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": layer["id"], "type": layer["type"], "source": source_id,
        "source-layer": layer["source_layer"], "minzoom": layer.get("minzoom", 0),
    }
    for section in ("layout", "paint"):
        if layer.get(section) is not None:
            result[section] = {
                key: _convert_style_value(key, value)
                for key, value in layer[section].items()
            }
    if layer.get("filter") is not None:
        result["filter"] = deepcopy(layer["filter"])
    return result


def _convert_style_value(property_name: str, value: Any) -> Any:
    if isinstance(value, dict) and "match" in value:
        match = value["match"]
        expression: list[Any] = ["match", ["get", match["field"]]]
        for key, case_value in match["cases"].items():
            expression.extend([key, _literalize(property_name, case_value)])
        expression.append(_literalize(property_name, match["default"]))
        return expression
    return _literalize(property_name, deepcopy(value))


def _literalize(property_name: str, value: Any) -> Any:
    if (
        property_name == "line-dasharray" and isinstance(value, list)
        and value and isinstance(value[0], (int, float)) and not isinstance(value[0], bool)
    ):
        return ["literal", deepcopy(value)]
    return deepcopy(value)


def _compile_text_layer(
    layer: dict[str, Any], source_id: str, locale: str,
    locale_config: dict[str, Any],
) -> dict[str, Any]:
    fonts = layer.get("font_stack_by_locale", {}).get(locale)
    fonts = fonts or locale_config.get("font_stack") or layer.get("font_stack") or ["NotoSans-Regular"]
    layout: dict[str, Any] = {
        "text-field": ["coalesce"] + [
            ["get", field] for field in locale_config["name_fields"]
        ],
        "text-font": deepcopy(fonts),
        "text-size": layer.get("text_size", 12),
        "text-anchor": "center",
        "text-allow-overlap": layer.get("text_allow_overlap", False),
        "text-ignore-placement": layer.get("text_ignore_placement", False),
        "text-optional": layer.get("text_optional", False),
        "symbol-placement": layer.get("placement", "point"),
    }
    if layer.get("symbol_spacing") is not None:
        layout["symbol-spacing"] = layer["symbol_spacing"]
    result: dict[str, Any] = {
        "id": layer["id"], "type": "symbol", "source": source_id,
        "source-layer": layer["source_layer"], "minzoom": layer.get("minzoom", 0),
        "layout": layout,
        "paint": {"text-color": "#1f2933", "text-halo-color": "#ffffff",
                  "text-halo-width": 1},
    }
    if layer.get("filter") is not None:
        result["filter"] = deepcopy(layer["filter"])
    return result


def _compile_bake(vector: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    bake = deepcopy(vector)
    bake.pop("glyphs", None)
    bake.pop("sprite", None)
    allowed = set(config.get("raster_overlays", {}).get(
        "bake_layer_types", ["background", "fill", "line"]
    ))
    bake["layers"] = [layer for layer in bake["layers"] if layer["type"] in allowed]
    for layer in bake["layers"]:
        dash = layer.get("paint", {}).get("line-dasharray")
        if layer["type"] == "line" and isinstance(dash, list) and dash[:1] == ["match"]:
            layer["paint"]["line-dasharray"] = dash[-1]
    return bake


def _compile_raster(vector: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    raster_source = config.get("raster_source", {})
    source_id = raster_source.get("id", "raster-bake")
    allowed = set(config.get("raster_overlays", {}).get(
        "vector_overlay_layer_types", ["symbol"]
    ))
    sources = deepcopy(vector["sources"])
    sources[source_id] = {
        "type": raster_source.get("type", "raster"),
        "url": raster_source.get("url", "pmtiles://{raster_pmtiles}"),
        "tileSize": raster_source.get("tile_size", 256),
    }
    background = [deepcopy(layer) for layer in vector["layers"] if layer["type"] == "background"]
    overlays = [deepcopy(layer) for layer in vector["layers"] if layer["type"] in allowed]
    raster: dict[str, Any] = {
        "version": vector["version"],
        "name": "HUAVD offline raster and vector overlay style",
        "glyphs": vector["glyphs"], "sources": sources,
        "layers": background + [{"id": "raster-baked-base", "type": "raster",
                                  "source": source_id}] + overlays,
        "metadata": {**deepcopy(vector["metadata"]), "huavd:asset-role": "raster-baked"},
    }
    if "sprite" in vector:
        raster["sprite"] = vector["sprite"]
    return raster
