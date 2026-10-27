import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.tippecanoe import TippecanoeRequest
from huavd_map_build.production.north.local.tippecanoe import TippecanoeService
from huavd_map_build.production.south.adapter.workspace.tippecanoe import (
    FileSystemTippecanoeWorkspace,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


class RecordingTippecanoeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: tuple[str, ...]) -> None:
        self.calls.append(arguments)


class TippecanoeServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.catalog = catalog_service(root)
        cls.configuration = build_configuration_service(root)

    def _service(self, runner: RecordingTippecanoeRunner) -> TippecanoeService:
        return TippecanoeService(
            self.catalog,
            self.configuration,
            FileSystemTippecanoeWorkspace(),
            runner,
        )

    def test_country_profile_builds_only_effective_layers_with_exact_flags(self) -> None:
        runner = RecordingTippecanoeRunner()
        with tempfile.TemporaryDirectory() as directory:
            session = SessionId("china-20261003")
            stage = Path(directory) / f"staging/{session}/layers"
            stage.mkdir(parents=True)
            layers = self.configuration.tippecanoe("china", "base")["source_layers"]
            for layer in layers:
                (stage / f"{layer}.geojsonseq").write_text("", encoding="utf-8")
            plan = self._service(runner).run(
                TippecanoeRequest(
                    RegionId("china"), BuildDate("20261003"), session,
                    Role.BASE, directory,
                )
            )
            self.assertEqual(11, len(plan.layer_paths))
            self.assertNotIn("building", dict(plan.layer_paths))
            self.assertIn("-Z0", plan.arguments)
            self.assertIn("-z10", plan.arguments)
            self.assertIn("--simplify-only-low-zooms", plan.arguments)
            self.assertIn("--drop-densest-as-needed", plan.arguments)
            self.assertIn("--maximum-tile-features=1000000", plan.arguments)
            self.assertFalse(any(arg.startswith("--limit-tile-feature-count") for arg in plan.arguments))
            self.assertEqual(
                f"{directory}/outputs/china-20261003.base.pmtiles", plan.output_path
            )
            self.assertEqual([plan.arguments], runner.calls)

    def test_building_retains_its_own_feature_budget(self) -> None:
        runner = RecordingTippecanoeRunner()
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "staging/china-guangxi-20261003/layers"
            stage.mkdir(parents=True)
            (stage / "building.geojsonseq").write_text("")
            plan = self._service(runner).run(TippecanoeRequest(
                RegionId("china/guangxi"), BuildDate("20261003"),
                SessionId("china-guangxi-20261003"), Role.BUILDING, directory,
            ))
        self.assertIn("--maximum-tile-features=200000", plan.arguments)
        self.assertFalse(any(arg.startswith("--limit-tile-feature-count") for arg in plan.arguments))

    def test_missing_layer_prevents_tool_execution(self) -> None:
        runner = RecordingTippecanoeRunner()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "building.geojsonseq"):
                self._service(runner).run(
                    TippecanoeRequest(
                        RegionId("china/guangxi"), BuildDate("20261003"),
                        SessionId("china-guangxi-20261003"), Role.BUILDING, directory,
                    )
                )
        self.assertEqual([], runner.calls)
