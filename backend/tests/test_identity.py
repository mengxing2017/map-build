import unittest

from huavd_map_build.shared.kernel import BuildDate, RegionId, SessionId
from huavd_map_build.shared.kernel.identity import DomainValidationError, expand_roles


class IdentityTest(unittest.TestCase):
    def test_session_matches_shell_contract(self) -> None:
        session = SessionId.for_build(RegionId("china/guangxi"), BuildDate("20260818"))
        self.assertEqual("china-guangxi-20260818", session.value)

    def test_role_expansions_match_shell_contract(self) -> None:
        self.assertEqual(
            ["base", "building", "raster_bake"],
            [role.value for role in expand_roles("both_raster")],
        )

    def test_invalid_date_is_rejected(self) -> None:
        with self.assertRaises(DomainValidationError):
            BuildDate("2026-08-18")
