from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path
from typing import Any, Sequence

import yaml

from huavd_map_build.catalog.south.adapter.yaml.loader import _SAFE_LOADER


SOUTH_AMERICA = frozenset("AR BO BR CL CO EC FK GF GY PE PY SR UY VE".split())
INDIAN_OVERRIDES = {
    "CC": "australia-oceania", "CX": "australia-oceania", "IO": "asia",
    "KM": "africa", "MG": "africa", "MV": "asia", "MU": "africa",
    "RE": "africa", "SC": "africa", "TF": "antarctica", "YT": "africa",
}
ATLANTIC_OVERRIDES = {
    "BM": "north-america", "CV": "africa", "FK": "south-america",
    "FO": "europe", "GS": "south-america", "IS": "europe", "PT": "europe",
    "SH": "africa",
}
COUNTRY_CONTINENT_OVERRIDES = {
    "AN": "north-america", "BV": "antarctica", "HM": "antarctica",
    "TP": "asia", "YU": "europe",
}


class FileSystemSkeletonSource:
    def __init__(self, zone_tab: str = "/usr/share/zoneinfo/zone.tab") -> None:
        self._zone_tab = Path(zone_tab)

    def csv_rows(self, path: str) -> tuple[Sequence[str], ...]:
        with Path(path).open("r", encoding="utf-8", newline="") as stream:
            return tuple(tuple(row) for row in csv.reader(stream))

    def yaml_document(self, path: str) -> dict[str, Any]:
        with Path(path).open("r", encoding="utf-8") as stream:
            document = yaml.load(stream, Loader=_SAFE_LOADER)
        if not isinstance(document, dict):
            raise ValueError(f"configuration root must be an object: {path}")
        return document

    def country_continents(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        if self._zone_tab.is_file():
            for line in self._zone_tab.read_text(encoding="utf-8").splitlines():
                if not line or line.startswith("#"):
                    continue
                fields = line.split("\t", 3)
                if len(fields) < 3 or fields[0] in mapping:
                    continue
                code, area = fields[0], fields[2].split("/", 1)[0]
                continent = {
                    "Africa": "africa", "Antarctica": "antarctica", "Asia": "asia",
                    "Australia": "australia-oceania", "Pacific": "australia-oceania",
                    "Europe": "europe", "Arctic": "europe",
                }.get(area)
                if area == "America":
                    continent = "south-america" if code in SOUTH_AMERICA else "north-america"
                elif area == "Indian":
                    continent = INDIAN_OVERRIDES.get(code)
                elif area == "Atlantic":
                    continent = ATLANTIC_OVERRIDES.get(code)
                if continent:
                    mapping[code] = continent
        mapping.update(COUNTRY_CONTINENT_OVERRIDES)
        return mapping

    def render_yaml(self, document: object) -> str:
        return yaml.safe_dump(
            document, allow_unicode=True, sort_keys=False, default_flow_style=False
        )

    def write_yaml(self, path: str, document: object) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        content = self.render_yaml(document)
        descriptor, temporary = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
