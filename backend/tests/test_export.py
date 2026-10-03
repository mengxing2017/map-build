import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.export import ExportRequest
from huavd_map_build.production.north.local.export import LayerExportService
from huavd_map_build.production.south.adapter.workspace.export import (
    FileSystemExportWorkspace,
)
from huavd_map_build.shared.kernel import RegionId, SessionId


class RecordingExportRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, bool]] = []

    def export(
        self, input_path: str, output_path: str, config_path: str,
        keep_untagged: bool,
    ) -> None:
        self.calls.append((input_path, output_path, config_path, keep_untagged))


class LayerExportServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = repository_root(Path(__file__))
        cls.catalog = catalog_service(cls.root)
        cls.configuration = build_configuration_service(cls.root)

    def _service(self, runner: RecordingExportRunner) -> LayerExportService:
        return LayerExportService(
            self.catalog,
            self.configuration,
            FileSystemExportWorkspace(),
            runner,
            str(self.root / "config"),
        )

    def test_stages_config_and_exports_to_session_layers(self) -> None:
        runner = RecordingExportRunner()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache/tags-filter"
            cache.mkdir(parents=True)
            for layer in ("road", "admin_line"):
                (cache / f"china-guangxi-{layer}.osm.pbf").write_bytes(b"fixture")
            plan = self._service(runner).run(
                ExportRequest(
                    RegionId("china/guangxi"),
                    SessionId("china-guangxi-20261003"),
                    directory,
                    "road,admin_line",
                )
            )
            staged = Path(directory) / "staging/china-guangxi-20261003"
            self.assertEqual(str(staged / "layers"), plan.layers_directory)
            self.assertTrue((staged / "export-config/road.json").is_file())
            self.assertEqual([False, True], [call[3] for call in runner.calls])
            self.assertEqual(str(staged / "layers/road.geojsonseq"), runner.calls[0][1])

    def test_preflights_every_input_before_copy_or_execution(self) -> None:
        runner = RecordingExportRunner()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "cache/tags-filter"
            cache.mkdir(parents=True)
            (cache / "china-guangxi-road.osm.pbf").write_bytes(b"fixture")
            with self.assertRaisesRegex(ValueError, "admin_line"):
                self._service(runner).run(
                    ExportRequest(
                        RegionId("china/guangxi"),
                        SessionId("china-guangxi-20261003"),
                        directory,
                        "road,admin_line",
                    )
                )
            staged = Path(directory) / "staging/china-guangxi-20261003/export-config"
            self.assertEqual([], runner.calls)
            self.assertEqual([], list(staged.iterdir()))
