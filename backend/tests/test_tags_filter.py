import tempfile
import unittest
from pathlib import Path

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.tags_filter import TagsFilterRequest
from huavd_map_build.production.north.local.tags_filter import TagsFilterService
from huavd_map_build.production.south.adapter.workspace.tags_filter import (
    FileSystemTagsFilterWorkspace,
)
from huavd_map_build.shared.kernel import RegionId


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[str, ...]]] = []

    def filter(
        self, input_path: str, output_path: str, filters: tuple[str, ...]
    ) -> None:
        self.calls.append((input_path, output_path, filters))


class TagsFilterServiceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = repository_root(Path(__file__))
        cls.catalog = catalog_service(root)
        cls.configuration = build_configuration_service(root)

    def test_filters_selected_layers_to_stable_cache_paths(self) -> None:
        runner = RecordingRunner()
        service = TagsFilterService(
            self.catalog,
            self.configuration,
            FileSystemTagsFilterWorkspace(),
            runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "mirror/source.osm.pbf"
            source.parent.mkdir()
            source.write_bytes(b"fixture")
            plan = service.run(
                TagsFilterRequest(
                    RegionId("china/guangxi"),
                    "mirror/source.osm.pbf",
                    directory,
                    "water,road",
                )
            )
            self.assertTrue(Path(plan.cache_directory).is_dir())
            self.assertEqual(["water", "road"], [task.layer for task in plan.tasks])
            self.assertEqual(str(source), plan.input_path)
            self.assertEqual(
                f"{directory}/cache/tags-filter/china-guangxi-water.osm.pbf",
                runner.calls[0][1],
            )
            self.assertTrue(runner.calls[0][2])

    def test_missing_input_fails_before_runner_is_called(self) -> None:
        runner = RecordingRunner()
        service = TagsFilterService(
            self.catalog,
            self.configuration,
            FileSystemTagsFilterWorkspace(),
            runner,
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "required file does not exist"):
                service.run(
                    TagsFilterRequest(
                        RegionId("china/guangxi"), "missing.osm.pbf", directory, "road"
                    )
                )
        self.assertEqual([], runner.calls)
