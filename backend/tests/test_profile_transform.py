import json
import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.profile_transform import (
    FeatureRule,
    LayerProfilePolicy,
    ProfileTransformRequest,
    transform_profile_feature,
)
from huavd_map_build.production.north.local.profile_transform import (
    ProfileTransformService,
)
from huavd_map_build.production.south.adapter.workspace.profile_transform import (
    FileSystemProfileTransformer,
)
from huavd_map_build.shared.kernel import RegionId, SessionId


def feature(properties, tippecanoe=None):
    value = {"type": "Feature", "properties": properties, "geometry": None}
    if tippecanoe is not None:
        value["tippecanoe"] = tippecanoe
    return value


class ProfileFeatureTest(unittest.TestCase):
    def test_first_matching_rule_sets_zoom_and_nonmatch_is_removed(self) -> None:
        policy = LayerProfilePolicy(
            "road", 0, 10,
            (
                FeatureRule({"highway": ["motorway"]}, 0, 6),
                FeatureRule({"highway": ["motorway", "primary"]}, 2, 10),
            ),
        )
        matched = transform_profile_feature(feature({"highway": "motorway"}), policy)
        self.assertEqual({"minzoom": 0, "maxzoom": 6}, matched["tippecanoe"])
        self.assertIsNone(transform_profile_feature(feature({"highway": "service"}), policy))

    def test_hierarchy_layer_intersects_existing_zoom(self) -> None:
        policy = LayerProfilePolicy(
            "place_label", 0, 10,
            (FeatureRule({"place": ["city"]}, 2, 8),),
        )
        result = transform_profile_feature(
            feature({"place": "city"}, {"minzoom": 5, "maxzoom": 12, "extra": 1}),
            policy,
        )
        self.assertEqual({"minzoom": 5, "maxzoom": 8}, result["tippecanoe"])


class ProfileTransformServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.configuration = build_configuration_service(root)
        cls.service = ProfileTransformService(
            catalog_service(root), cls.configuration, FileSystemProfileTransformer()
        )

    def test_applies_real_country_profile_as_stream(self) -> None:
        profile = self.configuration.profile_transform("china")
        names = [item["name"] for item in profile["layers"]]
        with tempfile.TemporaryDirectory() as directory:
            session = SessionId("china-20261003")
            stage = Path(directory) / f"staging/{session}/layers"
            stage.mkdir(parents=True)
            for name in names:
                (stage / f"{name}.geojsonseq").write_text("", encoding="utf-8")
            road = stage / "road.geojsonseq"
            road.write_text(
                "\x1e" + json.dumps(feature({"highway": "motorway"})) + "\n"
                + "\x1e" + json.dumps(feature({"highway": "service"})) + "\n",
                encoding="utf-8",
            )
            result = self.service.run(
                ProfileTransformRequest(
                    RegionId("china"), session, directory, ",".join(names)
                )
            )
            output = road.read_text(encoding="utf-8")
        self.assertEqual("country-low", result)
        self.assertEqual(1, output.count("\x1e"))
        self.assertIn('"maxzoom":10', output)
        self.assertNotIn("service", output)

    def test_region_without_profile_skips_workspace(self) -> None:
        result = self.service.run(
            ProfileTransformRequest(
                RegionId("china/guangxi"), SessionId("china-guangxi-20261003"),
                "/does/not/exist", "road",
            )
        )
        self.assertIsNone(result)

    def test_rejects_layer_order_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "do not match"):
            self.service.run(
                ProfileTransformRequest(
                    RegionId("china"), SessionId("china-20261003"),
                    "/does/not/exist", "railway,road",
                )
            )


class StandardZ19FeatureTest(unittest.TestCase):
    def test_high_detail_profile_preserves_hierarchy_and_local_labels(self):
        policy = LayerProfilePolicy("place_label", 2, 19, None)
        city = transform_profile_feature(feature({"label_tier": "prefecture"}, {"minzoom": 5, "maxzoom": 11}), policy)
        village = transform_profile_feature(feature({"label_tier": "locality"}, {"minzoom": 11}), policy)
        self.assertEqual({"minzoom": 5, "maxzoom": 11}, city["tippecanoe"])
        self.assertEqual({"minzoom": 11}, village["tippecanoe"])
        road = transform_profile_feature(feature({"highway": "service"}), LayerProfilePolicy("road", 0, 19, None))
        self.assertEqual(19, road["tippecanoe"]["maxzoom"])
