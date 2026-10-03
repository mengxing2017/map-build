from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.delivery.domain.artifact import ArtifactIdentity, ArtifactPaths
from huavd_map_build.quality.domain.style import StyleQualityReport, verify_style_contract
from huavd_map_build.quality.domain.vector import QualityFinding
from huavd_map_build.quality.south.port.style import StyleQualityReader
from huavd_map_build.shared.kernel import BuildDate, RegionId, Role


class StyleQualityGate:
    def __init__(
        self, configuration: BuildConfigurationService, reader: StyleQualityReader
    ) -> None:
        self._configuration, self._reader = configuration, reader

    def verify(
        self, *, region: RegionId, build_date: BuildDate, workdir: str
    ) -> StyleQualityReport:
        paths = ArtifactPaths(
            ArtifactIdentity(region, build_date, Role.BASE),
            f"{workdir.rstrip('/')}/outputs",
        )
        style = self._reader.read_json(paths.style)
        expected = tuple(
            self._configuration.tippecanoe(region.value, Role.BASE.value)["source_layers"]
        )
        detailed = self._configuration.profile_transform(region.value) is None
        report = verify_style_contract(style, expected, detailed)
        findings = list(report.findings)
        if not self._reader.sidecar_matches(paths.style):
            findings.append(QualityFinding(
                "style-sidecar",
                f"style has no matching SHA-512 sidecar: {paths.style}",
            ))
        self._verify_resources(paths, findings)
        return StyleQualityReport(tuple(findings))

    def _verify_resources(
        self, paths: ArtifactPaths, findings: list[QualityFinding]
    ) -> None:
        sprite_files = (f"{paths.sprite}/sprite.json", f"{paths.sprite}/sprite.png")
        for path in sprite_files:
            if not self._reader.sidecar_matches(path):
                findings.append(QualityFinding(
                    "style-sprite-resource",
                    f"sprite file or matching SHA-512 sidecar is missing: {path}",
                ))
        glyphs = self._reader.matching_files(paths.glyphs, ".pbf")
        if not glyphs:
            findings.append(QualityFinding(
                "style-glyph-resource", f"glyph directory has no PBF files: {paths.glyphs}"
            ))
        for path in glyphs:
            if not self._reader.sidecar_matches(path):
                findings.append(QualityFinding(
                    "style-glyph-resource",
                    f"glyph has no matching SHA-512 sidecar: {path}",
                ))
