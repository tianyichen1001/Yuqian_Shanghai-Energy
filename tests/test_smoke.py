"""Smoke tests — verify the package imports and the directory skeleton is intact."""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "module_name",
    [
        "buildings_shanghai",
        "buildings_shanghai.data",
        "buildings_shanghai.ml",
        "buildings_shanghai.simulation",
        "buildings_shanghai.embodied",
        "buildings_shanghai.calibration",
        "buildings_shanghai.viz",
    ],
)
def test_imports(module_name: str) -> None:
    """Every sub-module must be importable."""
    module = importlib.import_module(module_name)
    assert module is not None


def test_project_root_resolves() -> None:
    """``project_root()`` returns the repository root containing pyproject.toml."""
    from buildings_shanghai import project_root

    root = project_root()
    assert (root / "pyproject.toml").exists()
    assert (root / "CLAUDE.md").exists()


@pytest.mark.parametrize(
    "rel_path",
    [
        "config/shanghai.yaml",
        "config/archetypes.yaml",
        "config/poi_mapping.yaml",
        "config/standards.yaml",
        "config/calibration_targets.yaml",
    ],
)
def test_config_files_present(rel_path: str) -> None:
    """All five config YAMLs ship with the repo."""
    assert (PROJECT_ROOT / rel_path).is_file()


@pytest.mark.parametrize(
    "rel_path",
    [
        "scripts/run_module_a.py",
        "scripts/run_module_b.py",
        "scripts/run_module_c.py",
        "scripts/run_module_d.py",
        "scripts/run_module_e.py",
        "scripts/run_pipeline.py",
    ],
)
def test_scripts_present(rel_path: str) -> None:
    """All entry-point scripts ship with the repo."""
    assert (PROJECT_ROOT / rel_path).is_file()


def test_configs_parse_as_yaml() -> None:
    """The five config files are valid YAML (parseable, not necessarily complete)."""
    yaml = pytest.importorskip("yaml")
    for name in (
        "shanghai.yaml",
        "archetypes.yaml",
        "poi_mapping.yaml",
        "standards.yaml",
        "calibration_targets.yaml",
    ):
        path = PROJECT_ROOT / "config" / name
        with path.open("r", encoding="utf-8") as fh:
            yaml.safe_load(fh)
