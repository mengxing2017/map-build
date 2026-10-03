from __future__ import annotations

from pathlib import Path
import json
from typing import Any

import yaml


_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


class YamlAdapterError(RuntimeError):
    """Raised when a YAML document cannot be decoded at the system boundary."""


class PyYamlConfigurationRepository:
    def __init__(self, config_directory: Path) -> None:
        self._config_directory = config_directory

    def load(self, name: str) -> dict[str, Any]:
        relative = Path(name)
        if (
            not name or relative.is_absolute() or ".." in relative.parts
            or any(not part for part in relative.parts)
        ):
            raise YamlAdapterError(f"invalid configuration name: {name!r}")
        source = self._config_directory / relative.with_suffix(".yaml")
        if not source.is_file():
            raise YamlAdapterError(f"configuration does not exist: {source}")
        try:
            with source.open("r", encoding="utf-8") as stream:
                document = yaml.load(stream, Loader=_SAFE_LOADER)
        except (OSError, yaml.YAMLError) as error:
            raise YamlAdapterError(f"cannot decode {source}: {error}") from error
        if not isinstance(document, dict):
            raise YamlAdapterError(f"configuration root must be an object: {source}")
        return document

    def load_export(self, layer: str) -> dict[str, Any]:
        relative = Path(layer)
        if (
            not layer
            or relative.is_absolute()
            or len(relative.parts) != 1
            or relative.name != layer
        ):
            raise YamlAdapterError(f"invalid export configuration layer: {layer!r}")
        source = self._config_directory / "export-config" / f"{layer}.json"
        if not source.is_file():
            raise YamlAdapterError(f"export configuration does not exist: {source}")
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise YamlAdapterError(f"cannot decode {source}: {error}") from error
        if not isinstance(document, dict):
            raise YamlAdapterError(f"configuration root must be an object: {source}")
        return document
