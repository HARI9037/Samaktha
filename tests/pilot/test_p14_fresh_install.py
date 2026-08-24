from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGED_EXE = REPOSITORY_ROOT / "dist" / "samaktha" / "samaktha.exe"


def _packaged_env(local_app_data: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(local_app_data)
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for name in tuple(env):
        upper = name.upper()
        if (
            upper.endswith("_API_KEY")
            or upper.startswith("SMTP_")
            or upper in {"PYTHONHOME", "PYTHONPATH", "MOCK_AGENT"}
        ):
            env.pop(name, None)
    return env


def _run_packaged(
    args: list[str],
    *,
    local_app_data: Path,
    cwd: Path,
    timeout: float = 90.0,
) -> subprocess.CompletedProcess[str]:
    assert PACKAGED_EXE.is_file(), "Build the current ONEDIR package before P14 acceptance."
    return subprocess.run(
        [str(PACKAGED_EXE), *args],
        cwd=cwd,
        env=_packaged_env(local_app_data),
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )


def test_packaged_empty_state_bootstrap_and_offline_doctor_are_truthful(
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "Local AppData with spaces Ω"
    unrelated_cwd = tmp_path / "unrelated cwd 测试"
    unrelated_cwd.mkdir(parents=True)

    bootstrap = _run_packaged(
        ["bootstrap"], local_app_data=local_app_data, cwd=unrelated_cwd
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    assert "mode: installed" in bootstrap.stdout

    app_root = local_app_data / "Samaktha"
    expected_directories = {
        app_root / "config",
        app_root / "data",
        app_root / "cache",
        app_root / "logs",
        app_root / "workspace",
        app_root / "data" / "checkpoints",
        app_root / "plugins",
    }
    assert all(path.is_dir() for path in expected_directories)
    assert (app_root / "data" / "memory.db").is_file()
    assert (app_root / "data" / "evidence.db").is_file()

    doctor = _run_packaged(
        ["doctor"], local_app_data=local_app_data, cwd=unrelated_cwd
    )
    assert doctor.returncode == 1
    assert "Samaktha Diagnostics" in doctor.stdout
    assert "Groq ... ERROR" in doctor.stdout
    assert "Traceback" not in doctor.stderr
    key_path = app_root / "config" / "permit_signing.key"
    assert key_path.is_file()
    assert len(key_path.read_bytes()) == 32

    assert not (unrelated_cwd / "data").exists()
    combined = bootstrap.stdout + bootstrap.stderr + doctor.stdout + doctor.stderr
    assert str(REPOSITORY_ROOT).lower() not in combined.lower()
    assert ".venv" not in combined.lower()


def test_packaged_first_run_is_idempotent_and_preserves_signing_identity(
    tmp_path: Path,
) -> None:
    local_app_data = tmp_path / "state"
    cwd = tmp_path / "cwd"
    cwd.mkdir()

    first = _run_packaged(["bootstrap"], local_app_data=local_app_data, cwd=cwd)
    assert first.returncode == 0, first.stderr
    first_doctor = _run_packaged(["doctor"], local_app_data=local_app_data, cwd=cwd)
    assert first_doctor.returncode == 1

    app_root = local_app_data / "Samaktha"
    state_path = app_root / "config" / "bootstrap_state.json"
    key_path = app_root / "config" / "permit_signing.key"
    initial_state = json.loads(state_path.read_text(encoding="utf-8"))
    initial_key = key_path.read_bytes()

    for _ in range(3):
        repeated = _run_packaged(
            ["bootstrap"], local_app_data=local_app_data, cwd=cwd
        )
        assert repeated.returncode == 0, repeated.stderr
        assert json.loads(state_path.read_text(encoding="utf-8")) == initial_state
        assert key_path.read_bytes() == initial_key

    status = _run_packaged(
        ["bootstrap", "--status"], local_app_data=local_app_data, cwd=cwd
    )
    assert status.returncode == 0
    assert "State: current (v0.5.0)" in status.stdout


@pytest.mark.parametrize("suffix", ["path with spaces", "Unicode Ω 测试"])
def test_packaged_state_and_cwd_path_variations(tmp_path: Path, suffix: str) -> None:
    local_app_data = tmp_path / suffix / "LocalAppData"
    cwd = tmp_path / suffix / "launch cwd"
    cwd.mkdir(parents=True)

    version = _run_packaged(["--version"], local_app_data=local_app_data, cwd=cwd)
    assert version.returncode == 0
    assert version.stdout.strip() == "samaktha 0.5.0"

    bootstrap = _run_packaged(
        ["bootstrap"], local_app_data=local_app_data, cwd=cwd
    )
    assert bootstrap.returncode == 0, bootstrap.stderr
    assert (local_app_data / "Samaktha" / "data" / "memory.db").is_file()


def test_packaged_artifact_contains_no_source_checkout_state() -> None:
    assert PACKAGED_EXE.is_file()
    dist_root = PACKAGED_EXE.parent
    for name in ("data", "logs", ".cache", "config", "tests", ".git", ".venv"):
        assert not (dist_root / name).exists(), f"packaged mutable/developer path: {name}"

    prohibited_suffixes = {".py", ".pyc", ".pyo", ".db", ".key"}
    exposed = [
        path.relative_to(dist_root)
        for path in dist_root.rglob("*")
        if path.is_file() and path.suffix.lower() in prohibited_suffixes
    ]
    assert exposed == []
