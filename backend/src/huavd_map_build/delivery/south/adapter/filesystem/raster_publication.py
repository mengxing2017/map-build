from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile

from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths


class FileSystemRasterCandidatePublisher:
    def stage(
        self, candidate_pmtiles: str, identity: ArtifactIdentity,
        outputs_directory: str,
    ) -> ArtifactPaths:
        source = Path(candidate_pmtiles)
        if not source.is_file():
            raise ValueError(f"raster candidate does not exist: {candidate_pmtiles}")
        staging_root = Path(outputs_directory) / ".staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        directory = Path(tempfile.mkdtemp(
            prefix=f"{identity.stem}.", dir=staging_root
        ))
        paths = ArtifactPaths(identity, str(directory))
        temporary = Path(f"{paths.pmtiles}.tmp")
        shutil.copyfile(source, temporary)
        os.replace(temporary, paths.pmtiles)
        return paths

    def promote(self, staged: ArtifactPaths, final: ArtifactPaths) -> None:
        Path(final.outputs_directory).mkdir(parents=True, exist_ok=True)
        Path(final.ready).unlink(missing_ok=True)
        for source, target in (
            (staged.pmtiles, final.pmtiles),
            (staged.manifest, final.manifest),
            (staged.attribution, final.attribution),
        ):
            if not Path(source).is_file():
                raise ValueError(f"cannot publish missing staged artifact: {source}")
            os.replace(source, target)

    def discard(self, staged: ArtifactPaths) -> None:
        directory = Path(staged.outputs_directory)
        if directory.parent.name != ".staging":
            raise ValueError(f"refuse to discard non-staging directory: {directory}")
        shutil.rmtree(directory, ignore_errors=True)
