from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from huavd_map_build.quality.domain.vector import QualityFinding


@dataclass(frozen=True, slots=True)
class StyleQualityReport:
    findings: tuple[QualityFinding, ...]

    @property
    def passed(self) -> bool:
        return not self.findings

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "status": "passed" if self.passed else "failed",
            "findings": [finding.as_dict() for finding in self.findings],
        }


def verify_style_contract(
    style: dict[str, Any], expected_layers: tuple[str, ...], detailed: bool
) -> StyleQualityReport:
    findings: list[QualityFinding] = []

    def check(code: str, condition: bool, detail: str) -> None:
        if not condition:
            findings.append(QualityFinding(code, detail))

    layers = style.get("layers")
    sources = style.get("sources")
    glyphs = style.get("glyphs")
    sprite = style.get("sprite")
    check("style-version", style.get("version") == 8, "style version must be 8")
    check("style-sources", isinstance(sources, dict) and bool(sources),
          "style sources must be a non-empty object")
    check(
        "style-glyphs",
        isinstance(glyphs, str) and "{fontstack}" in glyphs and "{range}.pbf" in glyphs,
        "glyph URL must contain fontstack and range templates",
    )
    check(
        "style-sprite", isinstance(sprite, str) and sprite.startswith("huavd-map://sprite/"),
        "sprite URL must use huavd-map://sprite/",
    )
    if not isinstance(layers, list):
        findings.append(QualityFinding("style-layers", "style layers must be an array"))
        return StyleQualityReport(tuple(findings))
    source_layers = {
        layer.get("source-layer") for layer in layers
        if isinstance(layer, dict) and layer.get("source-layer") is not None
    }
    for unknown in sorted(source_layers - set(expected_layers)):
        findings.append(QualityFinding(
            "style-source-layer", f"style references absent source layer: {unknown}"
        ))
    if detailed:
        _verify_detailed_layers(layers, check)
    return StyleQualityReport(tuple(findings))


def _verify_detailed_layers(layers: list[Any], check) -> None:
    by_id = {
        layer.get("id"): layer for layer in layers
        if isinstance(layer, dict) and isinstance(layer.get("id"), str)
    }
    required = (
        "road-shield", "railway-labels", "island-labels", "peak-symbol",
        "transport-station-symbol", "highway-point-symbol", "poi-tourism-symbol",
        "poi-amenity-symbol",
        "place_label-city-labels", "place_label-locality-labels",
        "island-anchor-labels-large", "island-water-fill", "road-tunnel",
    )
    for layer_id in required:
        check("style-layer-missing", layer_id in by_id,
              f"required style layer is missing: {layer_id}")

    road = by_id.get("road-shield", {})
    check("style-road-source", road.get("source-layer") == "road",
          "road-shield must use road source layer")
    _contains(check, road, "layout", "text-field", "ref")
    _contains(check, road, "filter", None, "ref")
    _contains(check, road, "filter", None, "highway")
    _excludes(check, road, "filter", None, "network")
    _excludes(check, road, "filter", None, "int_ref")
    _before(check, layers, "railway-fill-dashed", "admin-0-boundary")
    _before(check, layers, "admin-2-boundary", "peak-symbol")
    for layer_id in ("admin-0-boundary", "admin-1-boundary", "admin-2-boundary"):
        _contains(check, by_id.get(layer_id, {}), "filter", None, "maritime")
        _contains(check, by_id.get(layer_id, {}), "filter", None, "yes")
    transport = by_id.get("transport-station-symbol", {})
    _contains(check, transport, "filter", None, '"station"')
    _contains(check, transport, "filter", None, '"halt"')
    _excludes(check, transport, "filter", None, '"stop"')
    _contains(check, transport, "layout", "icon-image", "rail-metro")
    _contains(check, transport, "layout", "icon-image", "rail-light")
    _before(check, layers, "place_label-city-labels", "place_label-locality-labels")
    _before(check, layers, "island-fill", "landuse")
    _before(check, layers, "water", "island-water-fill")
    _before(check, layers, "island-anchor-labels-large", "island-labels")
    highway = by_id.get("highway-point-symbol", {})
    _excludes(check, highway, "filter", None, "motorway_junction")
    _contains(check, highway, "layout", "icon-image", "services")
    _contains(check, highway, "layout", "icon-image", "rest-area")
    _excludes(check, by_id.get("poi-tourism-symbol", {}), "filter", None, '"information"')
    amenity = by_id.get("poi-amenity-symbol", {})
    _contains(check, amenity, "layout", "icon-image", "hospital")
    _contains(check, amenity, "layout", "icon-image", "school")
    for layer_id in ("transport-station-symbol", "highway-point-symbol", "poi-amenity-symbol"):
        layout = by_id.get(layer_id, {}).get("layout", {})
        for key in ("icon-allow-overlap", "icon-ignore-placement"):
            check("style-layout", layout.get(key) is True,
                  f"{layer_id} layout.{key} must be true")
    for layer_id in ("water", "island-fill", "island-water-fill", "railway-casing",
                     "railway-fill-solid", "railway-fill-dashed"):
        layer = by_id.get(layer_id, {})
        check(
            "style-paint", layer.get("type") in {"line", "fill", "circle", "background"}
            and isinstance(layer.get("paint"), dict) and bool(layer["paint"]),
            f"{layer_id} must be a paint layer with non-empty paint",
        )


def _serialized(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _contains(check, layer: dict, section: str, key: str | None, expected: str) -> None:
    value = layer.get(section)
    if key is not None:
        value = value.get(key) if isinstance(value, dict) else None
    check("style-expression", expected in _serialized(value),
          f"style layer {layer.get('id', '<missing>')} {section} must contain {expected}")


def _excludes(check, layer: dict, section: str, key: str | None, value: str) -> None:
    item = layer.get(section)
    if key is not None:
        item = item.get(key) if isinstance(item, dict) else None
    check("style-expression", value not in _serialized(item),
          f"style layer {layer.get('id', '<missing>')} {section} must exclude {value}")


def _before(check, layers: list[Any], before: str, after: str) -> None:
    ids = [layer.get("id") for layer in layers if isinstance(layer, dict)]
    valid = before in ids and after in ids and ids.index(before) < ids.index(after)
    check("style-layer-order", valid, f"style layer {before} must precede {after}")
