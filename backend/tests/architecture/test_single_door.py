"""The mechanical proof behind PRD §12.3: the gate is the only door.

These tests read the source tree with the :mod:`ast` module and fail the build if
the single-door invariant is ever broken by a future edit:

1. **Only the executor may reach a recovery channel.** If nothing outside
   ``recoup.execution.executor`` (and the channels package itself) imports
   ``recoup.channels``, then every path that runs a channel runs through the
   executor — which refuses to act without a verified gate pass.
2. **Only the gate may mint a pass.** If ``GatePass(...)`` is constructed in exactly
   one place, no other module can manufacture the token that authorises execution.

A reviewer reading a CI failure here should immediately see which invariant broke;
the assertion messages name the offending modules and the invariant.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "recoup"

# The executor is the sanctioned importer of the channels package; modules inside
# the channels package obviously import their own siblings.
_CHANNELS_IMPORT_ALLOWED = {"recoup.execution.executor"}
_CHANNELS_PACKAGE_PREFIX = "recoup.channels"

# GatePass is constructed only where it is defined (the gate) and reconstructed in
# tests; in the source tree, only the gate may build one.
_GATEPASS_CONSTRUCTOR_ALLOWED = {"recoup.constraints.gate"}


def _module_name(path: Path) -> str:
    rel = path.relative_to(_SRC_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _iter_source_modules() -> list[tuple[str, ast.Module]]:
    modules: list[tuple[str, ast.Module]] = []
    for path in sorted(_SRC_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        modules.append((_module_name(path), tree))
    return modules


def _imports_channels(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == _CHANNELS_PACKAGE_PREFIX or node.module.startswith(
                _CHANNELS_PACKAGE_PREFIX + "."
            ):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _CHANNELS_PACKAGE_PREFIX or alias.name.startswith(
                    _CHANNELS_PACKAGE_PREFIX + "."
                ):
                    return True
    return False


def _constructs_gatepass(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id == "GatePass":
                return True
            if isinstance(func, ast.Attribute) and func.attr == "GatePass":
                return True
    return False


def test_only_the_executor_imports_recovery_channels() -> None:
    offenders = [
        name
        for name, tree in _iter_source_modules()
        if name not in _CHANNELS_IMPORT_ALLOWED
        and not name.startswith(_CHANNELS_PACKAGE_PREFIX)
        and _imports_channels(tree)
    ]
    assert offenders == [], (
        "The gate is the only door (PRD 12.3): a recovery channel must be reachable "
        f"only through recoup.execution.executor, but these modules import "
        f"recoup.channels directly: {offenders}"
    )


def test_only_the_gate_constructs_a_gate_pass() -> None:
    offenders = [
        name
        for name, tree in _iter_source_modules()
        if name not in _GATEPASS_CONSTRUCTOR_ALLOWED and _constructs_gatepass(tree)
    ]
    assert offenders == [], (
        "A GatePass is the token that authorises execution; only the constraint gate "
        f"may mint one, but these modules construct GatePass directly: {offenders}"
    )
