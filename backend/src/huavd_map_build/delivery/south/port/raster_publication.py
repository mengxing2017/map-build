from typing import Protocol

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths


class RasterCandidatePublisher(Protocol):
    def stage(
        self, candidate_pmtiles: str, identity: ArtifactIdentity,
        outputs_directory: str,
    ) -> ArtifactPaths: ...

    def promote(self, staged: ArtifactPaths, final: ArtifactPaths) -> None: ...

    def discard(self, staged: ArtifactPaths) -> None: ...
