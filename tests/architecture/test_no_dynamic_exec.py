"""Architecture test enforcing Rule R5: No eval, exec, pickle, or shell=True."""

import ast
from pathlib import Path
from typing import List

APP_DIRS = (
    "app",
    "domain",
    "gestures",
    "camera",
    "workflows",
    "context",
    "services",
    "adapters",
    "database",
    "ui",
)


def test_no_forbidden_execution_constructs():
    repo_root = Path(__file__).resolve().parent.parent.parent
    violations: List[str] = []

    for dir_name in APP_DIRS:
        target_dir = repo_root / dir_name
        if not target_dir.exists():
            continue

        for py_file in target_dir.rglob("*.py"):
            with open(py_file, "r", encoding="utf-8") as f:
                try:
                    tree = ast.parse(f.read(), filename=str(py_file))
                except SyntaxError:
                    continue

            for node in ast.walk(tree):
                # 1. Check calls to eval() or exec()
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                        violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} uses forbidden {node.func.id}()")
                    # Check shell=True keyword argument
                    for kw in node.keywords:
                        if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} uses forbidden shell=True")

                # 2. Check imports of pickle
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "pickle" or alias.name.startswith("pickle."):
                            violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} imports forbidden 'pickle'")
                elif isinstance(node, ast.ImportFrom):
                    if node.module and (node.module == "pickle" or node.module.startswith("pickle.")):
                        violations.append(f"{py_file.relative_to(repo_root)}:{node.lineno} imports from forbidden 'pickle'")

    assert not violations, "Rule R5 Dynamic Execution Violations detected:\n" + "\n".join(violations)
