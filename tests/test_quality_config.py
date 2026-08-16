import tomllib
from pathlib import Path


def test_pyproject_configures_complete_local_quality_gate() -> None:
    repository_root = Path(__file__).resolve().parents[1]
    configuration = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    development_dependencies = configuration["project"]["optional-dependencies"]["dev"]

    assert any(dependency.startswith("ruff") for dependency in development_dependencies)
    assert any(dependency.startswith("mypy") for dependency in development_dependencies)
    assert any(
        dependency.startswith("pytest-cov") for dependency in development_dependencies
    )
    assert any(
        dependency.startswith("detect-secrets")
        for dependency in development_dependencies
    )
    assert "ruff" in configuration["tool"]
    assert "mypy" in configuration["tool"]
    assert "coverage" in configuration["tool"]
    assert (repository_root / "scripts" / "quality.py").is_file()
