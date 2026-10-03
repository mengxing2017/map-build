import hashlib
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    repository_root,
)
from huavd_map_build.production.domain.style import compile_styles
from huavd_map_build.quality.domain.style import verify_style_contract
from huavd_map_build.quality.north.local.style import StyleQualityGate
from huavd_map_build.quality.south.adapter.filesystem.style import (
    FileSystemStyleQualityReader,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId


class MemoryStyleReader:
    def __init__(self, style, files=(), valid_sidecars=()) -> None:
        self.style = style
        self.files = tuple(files)
        self.valid_sidecars = set(valid_sidecars)

    def read_json(self, path: str):
        del path
        return self.style

    def matching_files(self, directory: str, suffix: str):
        return tuple(
            path for path in self.files
            if path.startswith(f"{directory.rstrip('/')}/") and path.endswith(suffix)
        )

    def sidecar_matches(self, path: str) -> bool:
        return path in self.valid_sidecars


class StyleQualityDomainTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = build_configuration_service(repository_root(Path(__file__)))
        resolved = cls.configuration.style("china/guangxi", "zh-Hans")
        cls.style = compile_styles(
            resolved["config"], resolved["locale"], resolved["effective_base_layers"]
        ).vector
        cls.layers = tuple(resolved["effective_base_layers"])

    def test_compiled_style_passes_static_contract(self) -> None:
        report = verify_style_contract(self.style, self.layers, detailed=True)
        self.assertTrue(report.passed, report.as_dict())

    def test_reports_source_resource_and_detailed_layer_drift(self) -> None:
        style = {
            **self.style,
            "glyphs": "invalid",
            "sprite": "https://invalid/sprite",
            "layers": [
                *self.style["layers"],
                {"id": "unknown", "type": "line", "source-layer": "absent"},
            ],
        }
        style["layers"] = [
            layer for layer in style["layers"] if layer.get("id") != "road-shield"
        ]
        report = verify_style_contract(style, self.layers, detailed=True)
        codes = {finding.code for finding in report.findings}
        self.assertTrue({
            "style-glyphs", "style-sprite", "style-source-layer",
            "style-layer-missing",
        }.issubset(codes), report.as_dict())


class StyleQualityGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = build_configuration_service(repository_root(Path(__file__)))
        resolved = cls.configuration.style("china/guangxi", "zh-Hans")
        cls.style = compile_styles(
            resolved["config"], resolved["locale"], resolved["effective_base_layers"]
        ).vector

    def test_complete_style_resource_closure_passes(self) -> None:
        root = "/tmp/maps/outputs/china-guangxi-20261003"
        style_path = f"{root}.style.json"
        sprite_json = f"{root}.sprite/sprite.json"
        sprite_png = f"{root}.sprite/sprite.png"
        glyph = f"{root}.glyphs/zh-Hans/font/0-255.pbf"
        reader = MemoryStyleReader(
            self.style, files=(glyph,),
            valid_sidecars=(style_path, sprite_json, sprite_png, glyph),
        )
        report = StyleQualityGate(self.configuration, reader).verify(
            region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
            workdir="/tmp/maps",
        )
        self.assertTrue(report.passed, report.as_dict())

    def test_missing_resources_are_structured_findings(self) -> None:
        report = StyleQualityGate(
            self.configuration, MemoryStyleReader(self.style)
        ).verify(
            region=RegionId("china/guangxi"), build_date=BuildDate("20261003"),
            workdir="/tmp/maps",
        )
        codes = {finding.code for finding in report.findings}
        self.assertEqual(
            {"style-sidecar", "style-sprite-resource", "style-glyph-resource"}, codes
        )


class FileSystemStyleQualityReaderTest(unittest.TestCase):
    def test_validates_sha512_sidecar_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sprite.png"
            content = b"png"
            path.write_bytes(content)
            Path(f"{path}.sha512").write_text(
                f"{hashlib.sha512(content).hexdigest()}  sprite.png\n", encoding="utf-8"
            )
            reader = FileSystemStyleQualityReader()
            self.assertTrue(reader.sidecar_matches(str(path)))
            path.write_bytes(b"changed")
            self.assertFalse(reader.sidecar_matches(str(path)))
