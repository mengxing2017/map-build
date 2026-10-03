from datetime import datetime, timezone
from huavd_map_build.catalog.north.local.configuration import BuildConfigurationService
from huavd_map_build.catalog.north.local.service import CatalogService
from huavd_map_build.production.domain.glyph import GlyphRequest, plan_glyphs
from huavd_map_build.production.south.port.glyph import GlyphGenerator, GlyphWorkspace


class GlyphService:
    def __init__(
        self,
        catalog: CatalogService,
        configuration: BuildConfigurationService,
        generator: GlyphGenerator,
        workspace: GlyphWorkspace,
        repository_root: str,
    ) -> None:
        self._catalog = catalog
        self._configuration = configuration
        self._generator = generator
        self._workspace = workspace
        self._repository_root = repository_root

    def run(self, request: GlyphRequest) -> tuple[str, ...]:
        self._catalog.region(request.region)
        plan = plan_glyphs(
            self._configuration.glyph_manifest(), request.locales
        )
        resolved_fonts = {
            task.font.id: self._workspace.resolve_font(
                task.font.configured_file, self._repository_root
            )
            for task in plan.tasks
        }
        output = f"{request.workdir.rstrip('/')}/outputs/{request.session.value}.glyphs"
        staging = self._workspace.stage(output, request.force)
        try:
            for index, task in enumerate(plan.tasks):
                generated = self._workspace.prepare_generation(
                    staging, f".tmp-{index}-{task.font.id}"
                )
                self._generator.generate(
                    plan.generator, resolved_fonts[task.font.id], generated
                )
                self._workspace.install_fontstack(
                    generated,
                    f"{staging}/{task.locale}/{task.font.fontstack}",
                    task.font.fontstack,
                )
                self._workspace.discard(generated)
            manifest = {
                "schema": "huavd-map-glyphs/v1",
                "session": request.session.value,
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "available_locales": list(plan.available_locales),
                "url_template": plan.url_template,
            }
            return self._workspace.publish(staging, output, manifest)
        except BaseException:
            self._workspace.discard(staging)
            raise
