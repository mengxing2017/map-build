import json
import hashlib
import subprocess
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch
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
        railway = next(layer for layer in self.documents.vector["layers"] if layer["id"] == "railway-fill-solid")
        dash = railway["paint"]["line-dasharray"]
        self.assertEqual(["match", ["get", "railway"]], dash[:2])
        self.assertEqual(["literal", [3, 3]], dash[-1])
        amenity = next(
            layer for layer in self.documents.vector["layers"] if layer["id"] == "poi-amenity-symbol"
        )
        self.assertEqual(["match", ["get", "amenity"]], amenity["paint"]["text-color"][:2])

    def test_bake_style_removes_resources_symbols_and_uses_static_dash(self) -> None:
        bake = self.documents.bake
        self.assertNotIn("glyphs", bake)
        self.assertNotIn("sprite", bake)
        self.assertTrue(all(layer["type"] in {"background", "fill", "line"} for layer in bake["layers"]))
        railway = next(layer for layer in bake["layers"] if layer["id"] == "railway-fill-solid")
        self.assertEqual(["literal", [3, 3]], railway["paint"]["line-dasharray"])

    def test_raster_style_keeps_vector_symbol_support(self) -> None:
        raster = self.documents.raster
        ids = [layer["id"] for layer in raster["layers"]]
        self.assertEqual("background", ids[0])
        self.assertEqual("raster-baked-base", ids[1])
        self.assertTrue(all(layer["type"] in {"background", "raster", "symbol"} for layer in raster["layers"]))
        self.assertEqual(256, raster["sources"]["raster-bake"]["tileSize"])
        self.assertEqual("raster-baked", raster["metadata"]["huavd:asset-role"])

    def test_bake_contains_roads_and_land_cover_below_water(self) -> None:
        layers = self.documents.bake["layers"]
        ids = [layer["id"] for layer in layers]
        for layer_id in ("landuse", "natural-fill", "leisure-fill"):
            self.assertLess(ids.index(layer_id), ids.index("water"))
        self.assertLess(ids.index("water"), ids.index("road-road-casing"))
        self.assertLess(ids.index("road-road-casing"), ids.index("road-road-fill"))
        road = next(layer for layer in layers if layer["id"] == "road-road-fill")
        self.assertEqual("road", road["source-layer"])
        self.assertEqual(["!=", ["get", "tunnel"], True], road["filter"])

    def test_locale_and_pmtiles_url_overrides(self) -> None:
        resolved = self.configuration.style("china/guangxi", "en")
        vector = compile_styles(
            resolved["config"], "en", resolved["effective_base_layers"],
            pmtiles_url="pmtiles://manual.pmtiles",
        ).vector
        self.assertEqual("pmtiles://manual.pmtiles", vector["sources"]["huavd-offline"]["url"])
        place = next(layer for layer in vector["layers"] if layer["id"] == "place_label-city-labels")
        self.assertEqual(["get", "name:en"], place["layout"]["text-field"][1])

    def test_unknown_locale_is_rejected_by_configuration_boundary(self) -> None:
        with self.assertRaisesRegex(ValueError, "style locale is not configured"):
            self.configuration.style("china/guangxi", "missing")

    def test_localized_symbol_fields_and_derived_styles(self) -> None:
        locales = {
            "zh-Hans": (["name:zh-Hans", "name:zh", "name", "name:en"], "NotoSansCJKsc-Regular"),
            "en": (["name:en", "name:zh-Hans", "name"], "NotoSans-Regular"),
            "ja": (["name:ja", "name:en", "name:zh-Hans", "name"], "NotoSansCJKjp-Regular"),
            "ko": (["name:ko", "name:en", "name:zh-Hans", "name"], "NotoSansCJKkr-Regular"),
        }
        for locale, (names, font) in locales.items():
            with self.subTest(locale=locale):
                resolved = self.configuration.style("china/guangxi", locale)
                docs = compile_styles(resolved["config"], locale, resolved["effective_base_layers"])
                for layer in docs.vector["layers"]:
                    if layer["type"] != "symbol":
                        continue
                    self.assertEqual([font], layer["layout"]["text-font"])
                    if layer["id"] == "road-shield":
                        self.assertEqual(["get", "ref"], layer["layout"]["text-field"])
                    else:
                        prefix = [["get", "ref"]] if layer["id"] == "highway-point-symbol" else []
                        self.assertEqual(["coalesce", *prefix, *[["get", field] for field in names]],
                                         layer["layout"]["text-field"])
                self.assertEqual([layer for layer in docs.vector["layers"] if layer["type"] == "symbol"],
                                 [layer for layer in docs.raster["layers"] if layer["type"] == "symbol"])
                self.assertFalse(any(layer["type"] == "symbol" for layer in docs.bake["layers"]))

    def test_place_layers_split_administrative_and_locality_labels(self) -> None:
        by_id = {layer["id"]: layer for layer in self.documents.vector["layers"]}
        city, locality = by_id["place_label-city-labels"], by_id["place_label-locality-labels"]
        self.assertEqual(["!", city["filter"]], locality["filter"])
        self.assertEqual(0, city["minzoom"])
        self.assertEqual(11, locality["minzoom"])
        self.assertEqual([4, 12], city["layout"]["text-size"][3::2])
        self.assertEqual([11, 15], locality["layout"]["text-size"][3::2])
        self.assertIn("symbol-sort-key", city["layout"])
        self.assertNotIn("symbol-sort-key", locality["layout"])
        for layer in (city, locality):
            self.assertEqual("center", layer["layout"]["text-anchor"])
            self.assertNotIn("text-variable-anchor", layer["layout"])

    def test_explicit_layout_configuration_rejects_invalid_sections_and_prefix(self) -> None:
        resolved = self.configuration.style("china/guangxi", "zh-Hans")
        repository = self.configuration._repository
        original_load = repository.load
        for key, value in (("layout", []), ("paint", None), ("name_prefix_fields", [""]),
                           ("name_prefix_fields", "ref")):
            with self.subTest(key=key, value=value):
                config = deepcopy(resolved["config"])
                config["text_layers"][0][key] = value
                with patch.object(repository, "load", side_effect=lambda name: config if name == "styles" else original_load(name)):
                    with self.assertRaisesRegex(ValueError, "invalid styles configuration"):
                        self.configuration.style("china/guangxi", "zh-Hans")

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
        header[100:102] = bytes((0, 19))
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
        self.assertEqual(19, viewport["max_zoom"])


class RasterStyleBindingTest(unittest.TestCase):
    def test_raster_range_comes_from_its_header_not_the_vector_source(self):
        from unittest.mock import MagicMock
        from huavd_map_build.delivery.domain.metadata import PmtilesHeader
        from huavd_map_build.delivery.south.adapter.filesystem.atomic_writer import AtomicFileWriter
        from huavd_map_build.delivery.south.adapter.filesystem.digest import FileDigestAdapter
        from huavd_map_build.production.south.adapter.workspace.style import FileSystemRasterClientStyleBinder
        resolved = build_configuration_service(repository_root()).style("china/guangxi", "zh-Hans")
        document = compile_styles(resolved["config"], resolved["locale"], resolved["effective_base_layers"],
                                 {"min_zoom":0,"max_zoom":14}).raster
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"style-raster.json"
            path.write_text(json.dumps(document))
            headers=MagicMock(read=MagicMock(return_value=PmtilesHeader(4,1,0,19,(110,25,111,26))))
            FileSystemRasterClientStyleBinder(headers,AtomicFileWriter(),FileDigestAdapter()).bind("raster",str(path),256)
            bound=json.loads(path.read_text())
            self.assertEqual(19,bound["sources"]["raster-bake"]["maxzoom"])
            self.assertEqual(19,bound["metadata"]["huavd:viewport"]["max_zoom"])
            self.assertEqual([110,25,111,26],bound["sources"]["raster-bake"]["bounds"])
            self.assertEqual(14,bound["sources"]["huavd-offline"]["maxzoom"])
            self.assertIn(hashlib.sha512(path.read_bytes()).hexdigest(),Path(str(path)+".sha512").read_text())

    def test_recompiling_style_keeps_distinct_vector_and_raster_zooms(self):
        resolved = build_configuration_service(repository_root()).style("china/guangxi", "zh-Hans")
        docs = compile_styles(resolved["config"],resolved["locale"],resolved["effective_base_layers"],
            {"min_zoom":0,"max_zoom":14},raster_viewport={"min_zoom":2,"max_zoom":19,"bounds":[110,25,111,26]})
        self.assertEqual(14,docs.vector["sources"]["huavd-offline"]["maxzoom"])
        self.assertEqual(19,docs.raster["sources"]["raster-bake"]["maxzoom"])
        self.assertEqual(2,docs.raster["sources"]["raster-bake"]["minzoom"])

    def test_building_and_road_high_zoom_draw_order(self):
        resolved = build_configuration_service(repository_root()).style("china/guangxi", "zh-Hans")
        docs = compile_styles(resolved["config"],resolved["locale"],resolved["effective_base_layers"])
        ids=[layer['id'] for layer in docs.bake['layers']]
        self.assertLess(ids.index('building-fill'),ids.index('building-outline'))
        self.assertLess(ids.index('building-outline'),ids.index('road-road-casing'))
        self.assertLess(ids.index('road-road-casing'),ids.index('road-road-fill'))
