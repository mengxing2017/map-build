import unittest

from huavd_map_build.catalog.domain.model import CatalogValidationError
from huavd_map_build.catalog.domain.skeleton import (
    IsoHierarchy,
    SkeletonIds,
    slugify,
    stable_id_from_iso,
    unique_stable_id_from_iso,
)


class RegionSkeletonDomainTest(unittest.TestCase):
    def test_slugify_matches_ruby_transliteration_contract(self) -> None:
        self.assertEqual("sao-tome-and-principe", slugify("São Tomé & Príncipe"))
        self.assertEqual("unnamed", slugify("广西"))

    def test_stable_id_pads_single_character_iso_segments(self) -> None:
        self.assertEqual("us-0a-base", stable_id_from_iso("US-A"))
        self.assertEqual("cn-44-base", stable_id_from_iso("CN_44"))

    def test_stable_id_collision_uses_name_and_numeric_suffix(self) -> None:
        used = {"us-0a-base", "us-0a-alpha-base"}
        actual = unique_stable_id_from_iso("US-A", "Alpha", used)
        self.assertEqual("us-0a-alpha-2-base", actual)

    def test_planned_identity_maps_are_immutable(self) -> None:
        identities = SkeletonIds.plan(IsoHierarchy.parse([["CN", "", "", "China"]]))
        with self.assertRaises(TypeError):
            identities.country_ids["CN"] = "changed"  # type: ignore[index]

    def test_hierarchy_and_overrides_match_existing_generator(self) -> None:
        hierarchy = IsoHierarchy.parse(
            [
                ["CN", "", "", "China"],
                ["", "CN-44", "", "Guangdong"],
                ["", "", "CN-44-A", "Alpha District"],
                ["TW", "", "", "Taiwan"],
            ]
        )
        identities = SkeletonIds.plan(hierarchy)
        admin1 = hierarchy.subdivisions[0]
        admin2 = hierarchy.subdivisions[1]
        self.assertEqual("china", identities.country_ids["CN"])
        self.assertEqual("china/taiwan", identities.country_ids["TW"])
        self.assertEqual("china/guangdong", identities.subdivision_ids[admin1.key])
        self.assertEqual(
            "china/guangdong/alpha-district",
            identities.subdivision_ids[admin2.key],
        )
        self.assertEqual(admin1.key, admin2.parent_key)

    def test_admin1_without_country_is_rejected(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "without country"):
            IsoHierarchy.parse([["", "CN-44", "", "Guangdong"]])

    def test_admin2_without_admin1_is_rejected(self) -> None:
        with self.assertRaisesRegex(CatalogValidationError, "without admin-1"):
            IsoHierarchy.parse(
                [["CN", "", "", "China"], ["", "", "CN-44-A", "Alpha"]]
            )
