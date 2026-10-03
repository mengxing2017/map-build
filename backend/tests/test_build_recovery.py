import tempfile
import unittest
from pathlib import Path

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.production.domain.recovery import (
    ArtifactSetState,
    ExistingBuildArtifactsError,
)
from huavd_map_build.production.north.local.recovery import (
    BaseBuildPreparationService,
)
from huavd_map_build.production.south.adapter.workspace.recovery import (
    FileSystemBuildArtifactStore,
)
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class BaseBuildPreparationServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.paths = ArtifactPaths(
            ArtifactIdentity(
                RegionId("china/guangxi"), BuildDate("20261003"), Role.BASE
            ),
            str(Path(self.temporary.name) / "outputs"),
        )
        self.service = BaseBuildPreparationService(FileSystemBuildArtifactStore())

    @staticmethod
    def create(path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fixture", encoding="utf-8")

    def test_clean_workspace_requires_no_removal(self) -> None:
        result = self.service.prepare(self.paths)
        self.assertEqual(ArtifactSetState.CLEAN, result.state)
        self.assertEqual((), result.removed)

    def test_incomplete_artifacts_are_removed_without_force(self) -> None:
        self.create(self.paths.manifest)
        result = self.service.prepare(self.paths)
        self.assertEqual(ArtifactSetState.INCOMPLETE, result.state)
        self.assertEqual((self.paths.manifest,), result.removed)
        self.assertFalse(Path(self.paths.manifest).exists())

    def test_complete_artifacts_require_force(self) -> None:
        for path in self.paths.core_files():
            self.create(path)
        with self.assertRaisesRegex(ExistingBuildArtifactsError, "pass --force"):
            self.service.prepare(self.paths)
        self.assertTrue(all(Path(path).exists() for path in self.paths.core_files()))

    def test_force_removes_only_known_core_artifacts(self) -> None:
        for path in self.paths.core_files():
            self.create(path)
        unrelated = Path(self.paths.pmtiles).with_suffix(".metrics.json")
        self.create(str(unrelated))
        result = self.service.prepare(self.paths, force=True)
        self.assertEqual(ArtifactSetState.COMPLETE, result.state)
        self.assertEqual(self.paths.core_files(), result.removed)
        self.assertTrue(unrelated.exists())

    def test_broken_symlink_is_treated_as_incomplete_artifact(self) -> None:
        target = Path(self.paths.pmtiles)
        target.parent.mkdir(parents=True)
        target.symlink_to(target.parent / "missing.pmtiles")
        result = self.service.prepare(self.paths)
        self.assertEqual(ArtifactSetState.INCOMPLETE, result.state)
        self.assertFalse(target.is_symlink())
