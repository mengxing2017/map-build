from dataclasses import dataclass
from typing import Any

from huavd_map_build.shared.kernel import RegionId, SessionId


class MissingGlyphToolError(RuntimeError):
    pass


class GlyphExecutionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GlyphRequest:
    region: RegionId
    session: SessionId
    workdir: str
    locales: str = "all"
    force: bool = False


@dataclass(frozen=True, slots=True)
class GlyphFont:
    id: str
    fontstack: str
    configured_file: str


@dataclass(frozen=True, slots=True)
class GlyphTask:
    locale: str
    font: GlyphFont


@dataclass(frozen=True, slots=True)
class GlyphPlan:
    generator: str
    url_template: str
    available_locales: tuple[str, ...]
    tasks: tuple[GlyphTask, ...]


def plan_glyphs(document: dict[str, Any], selection: str) -> GlyphPlan:
    fonts = {
        item["id"]: GlyphFont(item["id"], item["fontstack"], item["file"])
        for item in document["fonts"]
    }
    locales = {item["tag"]: tuple(item["fonts"]) for item in document["locales"]}
    available = tuple(locales)
    if not selection or selection == "all":
        selected = available
    else:
        selected = tuple(tag for tag in selection.split(",") if tag)
        unknown = next((tag for tag in selected if tag not in locales), None)
        if unknown is not None:
            raise ValueError(f"unknown glyph locale: {unknown}")
    if not selected:
        raise ValueError("no glyph locales selected")
    tasks = tuple(
        GlyphTask(locale, fonts[font_id])
        for locale in selected
        for font_id in locales[locale]
    )
    generator = document["generator"]
    return GlyphPlan(
        generator["command"], generator["url_template"], available, tasks
    )
