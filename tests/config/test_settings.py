from app import __version__
from app.config.settings import Settings, resolve_sqlite_path


def test_canonical_version_matches_pyproject() -> None:
    import re
    from pathlib import Path

    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    declared = re.search(
        r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.MULTILINE
    ).group(1)

    assert __version__ == declared
    assert Settings().app_version == declared


def test_sqlite_url_is_canonical_database_source() -> None:
    assert Settings().sqlite_url.startswith("sqlite:///")


def test_resolve_sqlite_path_url_and_plain() -> None:
    assert resolve_sqlite_path("sqlite:///data/memory.db") == "data/memory.db"
    assert resolve_sqlite_path("sqlite:///./samaktha.db") == "./samaktha.db"
    assert resolve_sqlite_path("data/memory.db") == "data/memory.db"


def test_resolve_sqlite_path_rejects_remote_schemes() -> None:
    import pytest

    with pytest.raises(ValueError):
        resolve_sqlite_path("sqlite://user:pass@host/db")
