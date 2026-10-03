import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import build_configuration_service, repository_root
from huavd_map_build.production.domain.style import compile_styles
from huavd_map_build.production.domain.style import default_zoom
from huavd_map_build.production.south.adapter.process.pmtiles_viewport import (
    PmtilesViewportReader,
)


class StyleCompilerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.configuration = build_configuration_service(repository_root())
        resolved = cls.configuration.style("china/guangxi", "zh-Hans")
        cls.documents = compile_styles(
            resolved["config"], resolved["locale"], resolved["effective_base_layers"],
            {"center": [108.3, 23.8], "default_zoom": 6, "min_zoom": 0, "max_zoom": 18},
        )

    def test_vector_style_filters_layers_and_orders_symbols_last(self) -> None:
        style = self.documents.vector
        ids = [layer["id"] for layer in style["layers"]]
        types = [layer["type"] for layer in style["layers"]]
        first_symbol = types.index("symbol")
        self.assertTrue(all(value != "symbol" for value in types[:first_symbol]))
        self.assertEqual("background", ids[0])
        enabled = set(self.configuration.style(
            "china/guangxi", "zh-Hans"
        )["effective_base_layers"])
        self.assertTrue(all(
            layer.get("source-layer") in enabled
            for layer in style["layers"] if "source-layer" in layer
        ))
        self.assertEqual("zh-Hans", style["metadata"]["huavd:style-locale"])
        self.assertEqual(
            "huavd-map://glyphs/zh-Hans/{fontstack}/{range}.pbf", style["glyphs"]
        )

    def test_match_expressions_and_dash_arrays_match_maplibre_contract(self) -> None:
        railway = next(layer for layer in self.documents.vector["layers"] if layer["id"] == "railway")
        dash = railway["paint"]["line-dasharray"]
        self.assertEqual(["match", ["get", "railway"]], dash[:2])
        self.assertEqual(["literal", [1, 0]], dash[-1])
        amenity = next(
            layer for layer in self.documents.vector["layers"] if layer["id"] == "poi-amenity-symbol"
        )
        self.assertEqual(["match", ["get", "amenity"]], amenity["paint"]["text-color"][:2])

    def test_bake_style_removes_resources_symbols_and_uses_static_dash(self) -> None:
        bake = self.documents.bake
        self.assertNotIn("glyphs", bake)
        self.assertNotIn("sprite", bake)
        self.assertTrue(all(layer["type"] in {"background", "fill", "line"} for layer in bake["layers"]))
        railway = next(layer for layer in bake["layers"] if layer["id"] == "railway")
        self.assertEqual(["literal", [1, 0]], railway["paint"]["line-dasharray"])

    def test_raster_style_keeps_vector_symbol_support(self) -> None:
        raster = self.documents.raster
        ids = [layer["id"] for layer in raster["layers"]]
        self.assertEqual("background", ids[0])
        self.assertEqual("raster-baked-base", ids[1])
        self.assertTrue(all(layer["type"] in {"background", "raster", "symbol"} for layer in raster["layers"]))
        self.assertEqual(256, raster["sources"]["raster-bake"]["tileSize"])
        self.assertEqual("raster-baked", raster["metadata"]["huavd:asset-role"])

    def test_locale_and_pmtiles_url_overrides(self) -> None:
        resolved = self.configuration.style("china/guangxi", "en")
        vector = compile_styles(
            resolved["config"], "en", resolved["effective_base_layers"],
            pmtiles_url="pmtiles://manual.pmtiles",
        ).vector
        self.assertEqual("pmtiles://manual.pmtiles", vector["sources"]["huavd-offline"]["url"])
        place = next(layer for layer in vector["layers"] if layer["id"] == "place-label")
        self.assertEqual(["get", "name:en"], place["layout"]["text-field"][1])

    def test_unknown_locale_is_rejected_by_configuration_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "style locale is not configured"):
            self.configuration.style("china/guangxi", "missing")

    def test_compiler_matches_current_shell_documents_without_pmtiles(self) -> None:
        root = repository_root(Path(__file__))
        session = "china-guangxi-20261003"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                str(root / "scripts/style.sh"), "--region=china/guangxi",
                "--yyyymmdd=20261003", f"--session={session}",
                f"--workdir={directory}", "--locale=zh-Hans",
            ], cwd="/tmp", text=True, capture_output=True, timeout=30, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            vector = json.loads(
                (Path(directory) / f"outputs/{session}.style.json").read_text(encoding="utf-8")
            )
            bake = json.loads(
                (Path(directory) / f"cache/bake/{session}/style-render.json").read_text(encoding="utf-8")
            )
            raster = json.loads(
                (Path(directory) / f"outputs/{session}.style-raster.json").read_text(encoding="utf-8")
            )
            for relative in (
                f"outputs/{session}.style.json",
                f"cache/bake/{session}/style-render.json",
                f"outputs/{session}.style-raster.json",
            ):
                artifact = Path(directory) / relative
                sidecar = Path(f"{artifact}.sha512").read_text(encoding="utf-8")
                self.assertEqual(
                    f"{hashlib.sha512(artifact.read_bytes()).hexdigest()}  {artifact.name}\n",
                    sidecar,
                )
        resolved = self.configuration.style("china/guangxi", "zh-Hans")
        compiled = compile_styles(
            resolved["config"], resolved["locale"], resolved["effective_base_layers"]
        )
        self.assertEqual(vector, compiled.vector)
        self.assertEqual(bake, compiled.bake)
        self.assertEqual(raster, compiled.raster)

    def test_viewport_reads_header_and_falls_back_to_bounds_center(self) -> None:
        header = bytearray(127)
        import struct
        struct.pack_into("<iiii", header, 102, 100_000_000, 200_000_000,
                         120_000_000, 240_000_000)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "base.pmtiles"
            source.write_bytes(header)
            reader = PmtilesViewportReader()
            from unittest.mock import patch
            with patch.object(reader, "_decoder", return_value=None):
                viewport = reader.read(str(source))
        self.assertEqual([11.0, 22.0], viewport["center"])
        self.assertEqual(default_zoom((10.0, 20.0, 12.0, 24.0)), viewport["default_zoom"])
        self.assertEqual(0, viewport["min_zoom"])
        self.assertEqual(18, viewport["max_zoom"])
