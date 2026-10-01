"""Enforce allowed import directions, including future files in the core."""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "seenflow"


def test_domain_and_application_dependencies_point_inward():
    assert (ROOT / "application").is_dir(), "Application workflow must be separate from HTTP"
    violations = []
    for path in [ROOT / "models.py", ROOT / "matching.py", *(ROOT / "application").rglob("*.py")]:
        application = "application" in path.parts
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([alias.name for alias in node.names] if isinstance(node, ast.Import)
                     else [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            for name in names:
                root = name.split(".")[0]
                allowed = root in sys.stdlib_module_names or name in {"seenflow.models", "seenflow.matching"}
                if application:
                    allowed |= name.startswith("seenflow.application") or name == "PIL.Image"
                if not allowed:
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}: {name}")
    assert violations == [], "Outward core imports:\n" + "\n".join(violations)
