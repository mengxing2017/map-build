from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path
import tempfile

from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.production.domain.admin_line import AdminLineRequest
from huavd_map_build.production.domain.export import ExportRequest
from huavd_map_build.production.domain.island_anchor import IslandAnchorRequest
from huavd_map_build.production.domain.island_water import IslandWaterRequest
from huavd_map_build.production.domain.model import BuildPlan
from huavd_map_build.production.domain.normalize import NormalizeRequest
from huavd_map_build.production.domain.place_admin import PlaceAdminRequest
from huavd_map_build.production.domain.profile_transform import ProfileTransformRequest
from huavd_map_build.production.domain.tags_filter import TagsFilterRequest
from huavd_map_build.production.domain.tippecanoe import TippecanoeRequest
from huavd_map_build.production.domain.glyph import GlyphRequest
from huavd_map_build.production.domain.sprite import SpriteRequest
from huavd_map_build.production.domain.style import StyleRequest
from huavd_map_build.production.north.local.admin_line import AdminLineService
from huavd_map_build.production.north.local.export import LayerExportService
from huavd_map_build.production.north.local.island_anchor import IslandAnchorService
from huavd_map_build.production.north.local.island_water import IslandWaterService
from huavd_map_build.production.north.local.normalize import LayerNormalizationService
from huavd_map_build.production.north.local.place_admin import PlaceAdminService
from huavd_map_build.production.north.local.profile_transform import ProfileTransformService
from huavd_map_build.production.north.local.tags_filter import TagsFilterService
from huavd_map_build.production.north.local.tippecanoe import TippecanoeService
from huavd_map_build.production.north.local.glyph import GlyphService
from huavd_map_build.production.north.local.sprite import SpriteService
from huavd_map_build.production.north.local.style import StyleService
from huavd_map_build.quality.north.local.style import StyleQualityGate
from huavd_map_build.quality.domain.base import BaseDeepQualityError
from huavd_map_build.production.north.local.vector_finalize import (
    VectorFinalizationRequest,
    VectorFinalizationService,
)
from huavd_map_build.production.south.port.orchestration import (
    BaseDeepVerifier,
    BuildSourceWorkspace,
)
from huavd_map_build.shared.kernel import Role


class VectorBuildStageExecutor:
    def __init__(
        self, configuration: BuildConfigurationService,
        source: BuildSourceWorkspace, tags_filter: TagsFilterService,
        export: LayerExportService, normalize: LayerNormalizationService,
        place_admin: PlaceAdminService, island_water: IslandWaterService,
        island_anchor: IslandAnchorService, admin_line: AdminLineService,
        profile: ProfileTransformService, tippecanoe: TippecanoeService,
        finalizer: VectorFinalizationService, deep_verifier: BaseDeepVerifier,
        glyph: GlyphService, sprite: SpriteService, style: StyleService,
        style_quality: StyleQualityGate,
    ) -> None:
        self._configuration, self._source = configuration, source
        self._tags_filter, self._export, self._normalize = tags_filter, export, normalize
        self._place_admin, self._island_water = place_admin, island_water
        self._island_anchor, self._admin_line = island_anchor, admin_line
        self._profile, self._tippecanoe = profile, tippecanoe
        self._finalizer, self._deep_verifier = finalizer, deep_verifier
        self._glyph, self._sprite, self._style = glyph, sprite, style
        self._style_quality = style_quality

    def execute(self, stage_id: str, build: BuildPlan) -> None:
        if not build.roles or any(
            role not in (Role.BASE, Role.BUILDING) for role in build.roles
        ):
            raise ValueError("vector stage executor requires base/building roles")
        root, session = self._root(build), build.session.value
        layers = self._layers(build)
        source = f"{root}/staging/{session}/source.osm.pbf"
        if stage_id == "source-link":
            self._source.link(build.input_path, root, session)
        elif stage_id == "tags-filter":
            self._tags_filter.run(TagsFilterRequest(build.region, source, root, layers))
        elif stage_id == "export":
            self._export.run(ExportRequest(build.region, build.session, root, layers))
        elif stage_id == "normalize":
            self._normalize.run(NormalizeRequest(build.region, build.session, root, layers))
        elif stage_id == "place-admin-enrich":
            self._place_admin.run(PlaceAdminRequest(
                build.region, build.session, root, source
            ))
        elif stage_id == "island-water-flag":
            self._island_water.run(IslandWaterRequest(build.region, build.session, root))
        elif stage_id == "island-anchor":
            self._island_anchor.run(IslandAnchorRequest(build.region, build.session, root))
        elif stage_id == "admin-line-tier":
            self._admin_line.run(AdminLineRequest(
                build.region.value, build.build_date.value, root, session
            ))
        elif stage_id == "profile-transform":
            self._profile.run(ProfileTransformRequest(
                build.region, build.session, root, layers
            ))
        elif stage_id.startswith("tippecanoe:"):
            role = self._stage_role(stage_id, "tippecanoe", build)
            self._tippecanoe.run(TippecanoeRequest(
                build.region, build.build_date, build.session, role, root
            ))
        elif stage_id.startswith("finalize-vector:"):
            role = self._stage_role(stage_id, "finalize-vector", build)
            result = self._finalizer.run(VectorFinalizationRequest(
                build.region, build.build_date, build.session, role, root
            ))
            if not result.passed:
                raise RuntimeError("vector finalization quality gates failed")
        elif stage_id == "deep-verify:base":
            try:
                self._deep_verifier.verify(self._role_build(build, Role.BASE))
            except BaseDeepQualityError as error:
                self._write_deep_quality_report(build, error)
                raise
        elif stage_id == "glyph":
            self._glyph.run(GlyphRequest(
                build.region, build.session, root, force=True
            ))
        elif stage_id == "sprite":
            self._sprite.run(SpriteRequest(
                build.region, build.session, root, force=True
            ))
        elif stage_id == "style":
            self._style.run(StyleRequest(build.region, build.session, root))
        elif stage_id == "style-quality":
            report = self._style_quality.verify(
                region=build.region, build_date=build.build_date, workdir=root
            )
            if not report.passed:
                raise RuntimeError(
                    f"style quality gate failed with {len(report.findings)} finding(s)"
                )
        else:
            raise ValueError(f"unsupported vector build stage: {stage_id}")

    def _layers(self, build: BuildPlan) -> str:
        values: list[str] = []
        for role in build.roles:
            for layer in self._configuration.tippecanoe(
                build.region.value, role.value
            )["source_layers"]:
                if layer not in values:
                    values.append(layer)
        return ",".join(values)

    @staticmethod
    def _stage_role(stage_id: str, prefix: str, build: BuildPlan) -> Role:
        try:
            role = Role(stage_id.removeprefix(f"{prefix}:"))
        except ValueError as error:
            raise ValueError(f"unsupported vector build stage: {stage_id}") from error
        if role not in build.roles or role not in (Role.BASE, Role.BUILDING):
            raise ValueError(f"stage role is not part of build: {stage_id}")
        return role

    @staticmethod
    def _role_build(build: BuildPlan, role: Role) -> BuildPlan:
        if role not in build.roles:
            raise ValueError(f"role is not part of build: {role.value}")
        index = build.roles.index(role)
        return replace(
            build, roles=(role,), output_paths=(build.output_paths[index],)
        )

    @staticmethod
    def _root(build: BuildPlan) -> str:
        return build.workdir

    @staticmethod
    def _write_deep_quality_report(build: BuildPlan, error: BaseDeepQualityError) -> None:
        target = Path(build.workdir) / "staging" / build.session.value / "quality" / "base-deep.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=target.parent,
            prefix=".base-deep.", suffix=".tmp", delete=False,
        ) as stream:
            json.dump(error.report.as_dict(), stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            temporary = stream.name
        try:
            os.replace(temporary, target)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise


# Compatibility name for callers that still import the base-only executor.
BaseBuildStageExecutor = VectorBuildStageExecutor
