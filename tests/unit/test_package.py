"""The package must be importable and must agree with its own build metadata."""

import tomllib
from pathlib import Path

import recoup

PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict[str, object]:
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def test_package_version_matches_pyproject() -> None:
    """`GET /api/health` reports `recoup.__version__`, so it must not drift."""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert recoup.__version__ == project["version"]


def test_package_requires_python_313() -> None:
    """Python 3.13 is pinned for wheel coverage of the payment and telephony SDKs."""
    project = _pyproject()["project"]
    assert isinstance(project, dict)
    assert project["requires-python"] == ">=3.13"
