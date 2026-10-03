from huavd_map_build.delivery.domain.artifact import ArtifactPaths
from huavd_map_build.production.domain.recovery import (
    ArtifactSetState,
    BuildPreparationResult,
    ExistingBuildArtifactsError,
)
from huavd_map_build.production.south.port.recovery import BuildArtifactStore


class VectorBuildPreparationService:
    def __init__(self, store: BuildArtifactStore) -> None:
        self._store = store

    def prepare(
        self, paths: ArtifactPaths, *, force: bool = False
    ) -> BuildPreparationResult:
        expected = paths.core_files()
        existing = self._store.existing(expected)
        if not existing:
            return BuildPreparationResult(ArtifactSetState.CLEAN)
        state = (
            ArtifactSetState.COMPLETE
            if len(existing) == len(expected)
            else ArtifactSetState.INCOMPLETE
        )
        if state is ArtifactSetState.COMPLETE and not force:
            raise ExistingBuildArtifactsError(
                f"output already exists: {paths.pmtiles}; pass --force or clean first"
            )
        return BuildPreparationResult(state, self._store.remove(existing))


BaseBuildPreparationService = VectorBuildPreparationService
