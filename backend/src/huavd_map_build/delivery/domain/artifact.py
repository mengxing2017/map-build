from __future__ import annotations

from dataclasses import dataclass

from huavd_map_build.shared.kernel import BuildDate, RegionId, Role, SessionId


class ArtifactContractError(ValueError):
    """Raised when an artifact set violates the delivery contract."""


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    region: RegionId
    build_date: BuildDate
    role: Role

    @property
    def session(self) -> SessionId:
        return SessionId.for_build(self.region, self.build_date)

    @property
    def stem(self) -> str:
        return f"{self.region.slug}-{self.build_date.value}.{self.role.value}"


@dataclass(frozen=True, slots=True)
class ArtifactPaths:
    identity: ArtifactIdentity
    outputs_directory: str

    def _join(self, name: str) -> str:
        return f"{self.outputs_directory.rstrip('/')}/{name}"

    @property
    def pmtiles(self) -> str:
        return self._join(f"{self.identity.stem}.pmtiles")

    @property
    def manifest(self) -> str:
        return self._join(f"{self.identity.stem}.manifest.json")

    @property
    def attribution(self) -> str:
        return self._join(f"{self.identity.stem}.attribution.json")

    @property
    def sha512(self) -> str:
        return self._join(f"{self.identity.stem}.pmtiles.sha512")

    @property
    def ready(self) -> str:
        return self._join(f"{self.identity.stem}.ready.json")

    @property
    def style(self) -> str:
        return self._join(f"{self.identity.session.value}.style.json")

    @property
    def raster_style(self) -> str:
        return self._join(f"{self.identity.session.value}.style-raster.json")

    @property
    def glyphs(self) -> str:
        return self._join(f"{self.identity.session.value}.glyphs")

    @property
    def sprite(self) -> str:
        return self._join(f"{self.identity.session.value}.sprite")

    def core_files(self) -> tuple[str, ...]:
        return (self.pmtiles, self.sha512, self.manifest, self.attribution)

    def consumer_closure(self) -> tuple[str, ...]:
        if self.identity.role is not Role.RASTER_BAKE:
            return self.core_files()
        base = ArtifactPaths(
            ArtifactIdentity(
                self.identity.region, self.identity.build_date, Role.BASE
            ),
            self.outputs_directory,
        )
        return (
            *self.core_files(),
            *base.core_files(),
            self.style,
            f"{self.style}.sha512",
            self.raster_style,
            f"{self.raster_style}.sha512",
            self.glyphs,
            self.sprite,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "region": self.identity.region.value,
            "yyyymmdd": self.identity.build_date.value,
            "session": self.identity.session.value,
            "role": self.identity.role.value,
            "stem": self.identity.stem,
            "pmtiles": self.pmtiles,
            "manifest": self.manifest,
            "attribution": self.attribution,
            "sha512": self.sha512,
            "ready": self.ready,
            "consumer_closure": list(self.consumer_closure()),
        }
