"""Architecture tests enforcing structural separation and import boundaries."""

import ast
from pathlib import Path
from typing import List, Set


def get_imports_from_file(file_path: Path) -> Set[str]:
    """Parses a Python file and returns all imported module names."""
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


def test_rule_r1_ui_separation():
    """Rule R1: ui/ MUST NOT import workflow execution, adapters, win32*, sqlite3, or cv2."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    ui_dir = repo_root / "ui"
    if not ui_dir.exists():
        return

    forbidden_prefixes = (
        "workflows.workflow_executor",
        "workflows.execution_dispatcher",
        "adapters",
        "win32",
        "sqlite3",
        "cv2",
    )

    violations: List[str] = []
    for py_file in ui_dir.rglob("*.py"):
        imports = get_imports_from_file(py_file)
        for imp in imports:
            for forbidden in forbidden_prefixes:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append(f"{py_file.name} imports forbidden '{imp}'")

    assert not violations, f"Rule R1 Violations:\n" + "\n".join(violations)


def test_rule_domain_purity():
    """Domain layer MUST NOT import Qt, OpenCV, SQLite, or OS adapters."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    domain_dir = repo_root / "domain"
    if not domain_dir.exists():
        return

    forbidden_prefixes = (
        "PySide6",
        "cv2",
        "sqlite3",
        "adapters",
        "win32",
        "ui",
        "workflows.workflow_executor",
    )

    violations: List[str] = []
    for py_file in domain_dir.rglob("*.py"):
        imports = get_imports_from_file(py_file)
        for imp in imports:
            for forbidden in forbidden_prefixes:
                if imp == forbidden or imp.startswith(forbidden + "."):
                    violations.append(f"{py_file.name} imports forbidden '{imp}'")

    assert not violations, f"Domain Purity Violations:\n" + "\n".join(violations)


def test_rule_r2_recognition_isolation():
    """Rule R2: gestures/ and camera/ MUST NOT import workflows.*, services.*, or adapters.*."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    check_dirs = [repo_root / "gestures", repo_root / "camera"]

    forbidden_prefixes = (
        "workflows",
        "services",
        "adapters",
    )

    violations: List[str] = []
    for directory in check_dirs:
        if not directory.exists():
            continue
        for py_file in directory.rglob("*.py"):
            imports = get_imports_from_file(py_file)
            for imp in imports:
                for forbidden in forbidden_prefixes:
                    if imp == forbidden or imp.startswith(forbidden + "."):
                        violations.append(f"{py_file.name} imports forbidden '{imp}'")

    assert not violations, f"Rule R2 Violations:\n" + "\n".join(violations)


def test_rule_r4_diagnostic_sink_isolation():
    """Rule R4: DiagnosticSink must have no import paths to execution gate, dispatcher, executor, or adapters."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    sink_file = repo_root / "services" / "diagnostic_sink.py"
    if not sink_file.exists():
        return

    forbidden_prefixes = (
        "services.execution_gate",
        "workflows.execution_dispatcher",
        "workflows.workflow_executor",
        "adapters",
    )

    imports = get_imports_from_file(sink_file)
    violations: List[str] = []
    for imp in imports:
        for forbidden in forbidden_prefixes:
            if imp == forbidden or imp.startswith(forbidden + "."):
                violations.append(f"diagnostic_sink.py imports forbidden '{imp}'")

    assert not violations, f"Rule R4 Violations:\n" + "\n".join(violations)


def test_rule_r10_sqlite_isolation():
    """Rule R10: Only database/ may import sqlite3."""
    repo_root = Path(__file__).resolve().parent.parent.parent
    check_dirs = [
        repo_root / "domain",
        repo_root / "gestures",
        repo_root / "camera",
        repo_root / "ui",
    ]

    violations: List[str] = []
    for directory in check_dirs:
        if not directory.exists():
            continue
        for py_file in directory.rglob("*.py"):
            imports = get_imports_from_file(py_file)
            if "sqlite3" in imports:
                violations.append(f"{py_file.name} imports sqlite3 outside database/")

    assert not violations, f"Rule R10 Violations:\n" + "\n".join(violations)

