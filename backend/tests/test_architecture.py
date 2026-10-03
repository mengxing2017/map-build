import ast
import unittest
from pathlib import Path


class ArchitectureTest(unittest.TestCase):
    def test_domain_modules_do_not_import_infrastructure(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src/huavd_map_build"
        forbidden = {"subprocess", "pathlib", "yaml", "pydantic", "fastapi"}
        violations: list[str] = []
        for path in root.glob("*/domain/*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = {node.module.split(".")[0]}
                else:
                    continue
                if names & forbidden:
                    violations.append(f"{path}: {sorted(names & forbidden)}")
        self.assertEqual([], violations)
