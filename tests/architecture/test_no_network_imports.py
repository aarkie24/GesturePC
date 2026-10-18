"""Architecture test enforcing strict zero-network-access policy (Rule R11)."""

import ast
from pathlib import Path
from typing import List, Set

FORBIDDEN_NETWORK_MODULES = (
    "requests",
    "urllib.request",
    "http.client",
    "socket",
    "aiohttp",
    "httpx",
    "ftplib",
    "smtplib",
)

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


def get_imports_from_file(file_path: Path) -> Set[str]:
    with open(file_path, "r", encoding="utf-8") as f:
        try:
            tree = ast.parse(f.read(), filename=str(file_path))
        except SyntaxError:
            return set()

    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
    return imports


def test_zero_network_imports_in_application_code():
    repo_root = Path(__file__).resolve().parent.parent.parent
    violations: List[str] = []

    for dir_name in APP_DIRS:
        target_dir = repo_root / dir_name
        if not target_dir.exists():
            continue

        for py_file in target_dir.rglob("*.py"):
            imports = get_imports_from_file(py_file)
            for imp in imports:
                for forbidden in FORBIDDEN_NETWORK_MODULES:
                    if imp == forbidden or imp.startswith(forbidden + "."):
                        violations.append(f"{py_file.relative_to(repo_root)} imports network module '{imp}'")

    assert not violations, "Zero-Network Policy Violations detected:\n" + "\n".join(violations)
