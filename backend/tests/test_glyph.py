import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from huavd_map_build.bootstrap import (
    build_configuration_service,
    catalog_service,
    repository_root,
)
from huavd_map_build.production.domain.glyph import (
    GlyphExecutionError,
    GlyphRequest,
    MissingGlyphToolError,
    plan_glyphs,
)
from huavd_map_build.production.north.local.glyph import GlyphService
from huavd_map_build.production.south.adapter.process.glyph import (
    ProcessGlyphGenerator,
)
from huavd_map_build.production.south.adapter.workspace.glyph import (
    FileSystemGlyphWorkspace,
)
from huavd_map_build.shared.kernel import RegionId, SessionId


class FakeGlyphGenerator:
    def __init__(self) -> None:
        self.fail = False

    def generate(self, command: str, font_path: str, output_directory: str) -> None:
        if self.fail:
            raise GlyphExecutionError("fixture failure")
        target = Path(output_directory) / "generated/0-255.pbf"
        target.parent.mkdir()
        target.write_bytes(f"{command}:{Path(font_path).name}".encode("utf-8"))


class GlyphPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.document = build_configuration_service(repository_root()).glyph_manifest()

    def test_all_locales_preserve_configuration_order(self) -> None:
        plan = plan_glyphs(self.document, "all")
        self.assertEqual(("zh-Hans", "en", "ja", "ko"), plan.available_locales)
        self.assertEqual(7, len(plan.tasks))
        self.assertEqual("zh-Hans", plan.tasks[0].locale)
        self.assertEqual("NotoSansCJKsc-Regular", plan.tasks[0].font.fontstack)
        self.assertEqual("build-glyphs", plan.generator)

    def test_explicit_locale_order_and_unknown_validation(self) -> None:
        plan = plan_glyphs(self.document, "ko,en")
        self.assertEqual(["ko", "ko", "en"], [task.locale for task in plan.tasks])
        with self.assertRaisesRegex(ValueError, "unknown glyph locale: missing"):
            plan_glyphs(self.document, "en,missing")


class ProcessGlyphGeneratorTest(unittest.TestCase):
    def test_finds_installed_wrapper_without_user_directories_on_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            wrapper = home / ".local/bin/build-glyphs"
            wrapper.parent.mkdir(parents=True)
            wrapper.write_text("#!/bin/sh\nexit 0\n")
            wrapper.chmod(0o755)
            cargo = home / "custom-cargo/bin"
            cargo.mkdir(parents=True)
            (cargo / "versatiles_glyphs").touch()
            with patch.dict("os.environ", {
                "HOME": directory, "PATH": "/usr/bin:/bin",
                "CARGO_HOME": str(cargo.parent),
            }, clear=True), patch(
                "subprocess.run", return_value=Mock(returncode=0)
            ) as run:
                ProcessGlyphGenerator().generate("build-glyphs", "font", "output")
            self.assertEqual(str(wrapper), run.call_args.args[0][0])
            self.assertEqual(
                f"{cargo}:/usr/bin:/bin", run.call_args.kwargs["env"]["PATH"]
            )

    def test_executes_argument_vector_with_restricted_environment(self) -> None:
        completed = Mock(returncode=0)
        with patch("shutil.which", return_value="/tools/build-glyphs"), patch(
            "subprocess.run", return_value=completed
        ) as run:
            ProcessGlyphGenerator().generate(
                "build-glyphs", "/fonts/a.ttf", "/tmp/output"
            )
        arguments, keywords = run.call_args
        self.assertEqual(
            ["/tools/build-glyphs", "/fonts/a.ttf", "/tmp/output"], arguments[0]
        )
        self.assertFalse(keywords["check"])
        self.assertNotIn("PYTHONPATH", keywords["env"])

    def test_maps_missing_tool_and_nonzero_exit(self) -> None:
        with patch("shutil.which", return_value=None):
            with self.assertRaises(MissingGlyphToolError):
                ProcessGlyphGenerator().generate("missing", "font", "output")
        with patch("shutil.which", return_value="/tool"), patch(
            "subprocess.run", return_value=Mock(returncode=9)
        ):
            with self.assertRaisesRegex(GlyphExecutionError, "exit code 9"):
                ProcessGlyphGenerator().generate("tool", "font", "output")

    def test_build_glyphs_wrapper_receives_cargo_binary_path(self) -> None:
        with patch.dict(
            "os.environ", {"HOME": "/home/test", "PATH": "/tools"}, clear=True
        ), patch("shutil.which", return_value="/tools/build-glyphs"), patch(
            "os.path.isfile", return_value=True
        ), patch("subprocess.run", return_value=Mock(returncode=0)) as run:
            ProcessGlyphGenerator().generate("build-glyphs", "font", "output")
        self.assertEqual(
            "/home/test/.cargo/bin:/tools", run.call_args.kwargs["env"]["PATH"]
        )


class GlyphServiceTest(unittest.TestCase):
    def test_publishes_manifest_sidecars_and_preserves_previous_on_failure(self) -> None:
        root = repository_root(Path(__file__))
        generator = FakeGlyphGenerator()
        service = GlyphService(
            catalog_service(root), build_configuration_service(root), generator,
            FileSystemGlyphWorkspace(), str(root),
        )
        with tempfile.TemporaryDirectory() as directory:
            request = GlyphRequest(
                RegionId("china/guangxi"), SessionId("china-guangxi-20261003"),
                directory, "en", False,
            )
            paths = service.run(request)
            self.assertEqual(2, len(paths))
            manifest = Path(paths[-1])
            document = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual("huavd-map-glyphs/v1", document["schema"])
            self.assertEqual(["zh-Hans", "en", "ja", "ko"], document["available_locales"])
            for path in map(Path, paths):
                self.assertEqual(
                    f"{hashlib.sha512(path.read_bytes()).hexdigest()}  {path.name}\n",
                    Path(f"{path}.sha512").read_text(encoding="ascii"),
                )
            original = manifest.read_bytes()
            generator.fail = True
            with self.assertRaisesRegex(GlyphExecutionError, "fixture failure"):
                service.run(GlyphRequest(
                    request.region, request.session, directory, "en", True
                ))
            self.assertEqual(original, manifest.read_bytes())
            self.assertFalse(any(
                path.name.startswith(".china-guangxi-20261003.glyphs.")
                for path in manifest.parent.parent.iterdir()
            ))
