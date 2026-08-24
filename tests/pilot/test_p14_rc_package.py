from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DIST_ROOT = REPOSITORY_ROOT / "dist" / "samaktha"
PACKAGED_EXE = DIST_ROOT / "samaktha.exe"


def _run(args: list[str], root: Path, cwd: Path, **extra_env: str):
    env = os.environ.copy()
    env.update(
        {
            "LOCALAPPDATA": str(root),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            **extra_env,
        }
    )
    for name in tuple(env):
        if name.upper().endswith("_API_KEY") or name.upper().startswith("SMTP_"):
            env.pop(name, None)
    env.update(extra_env)
    return subprocess.run(
        [str(PACKAGED_EXE), *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        shell=False,
    )


def test_rc_packaged_doctor_exports_only_safe_local_diagnostics(
    tmp_path: Path,
) -> None:
    state_root = tmp_path / "RC LocalAppData"
    cwd = tmp_path / "launch"
    cwd.mkdir()
    sentinel = "P14-RC-SECRET-NEVER-EXPORT"

    bootstrap = _run(["bootstrap"], state_root, cwd)
    assert bootstrap.returncode == 0, bootstrap.stderr
    doctor = _run(
        ["doctor", "--export"],
        state_root,
        cwd,
        P14_PRIVATE_ENV_VALUE=sentinel,
    )
    assert doctor.returncode == 1
    assert "Diagnostic bundle written locally:" in doctor.stdout
    assert "No diagnostic data was uploaded." in doctor.stdout

    exported = list(
        (state_root / "Samaktha" / "cache" / "diagnostics").glob("*.json")
    )
    assert len(exported) == 1
    raw = exported[0].read_text(encoding="utf-8")
    assert sentinel not in raw
    payload = json.loads(raw)
    assert payload["application"]["mode"] == "installed"
    assert payload["privacy"]["uploaded"] is False
    assert all(value is False for key, value in payload["privacy"].items() if key != "uploaded")
    assert not (cwd / "data").exists()


def test_rc_package_runs_without_python_on_path(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    minimal_path = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32")
    result = _run(
        ["--version"],
        tmp_path / "state",
        cwd,
        PATH=minimal_path,
        PYTHONHOME="",
        PYTHONPATH="",
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "samaktha 0.5.0"


def test_rc_artifact_hash_and_source_path_scan_are_clean() -> None:
    assert PACKAGED_EXE.is_file()
    digest = hashlib.sha256(PACKAGED_EXE.read_bytes()).hexdigest()
    assert len(digest) == 64
    assert digest != "0" * 64

    prohibited = [
        str(REPOSITORY_ROOT).encode("utf-8"),
        str(REPOSITORY_ROOT).encode("utf-16le"),
        b".venv\\Scripts\\python.exe",
    ]
    for path in DIST_ROOT.rglob("*"):
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            overlap = b""
            while chunk := handle.read(1_048_576):
                data = overlap + chunk
                assert not any(marker in data for marker in prohibited), path
                overlap = data[-512:]
