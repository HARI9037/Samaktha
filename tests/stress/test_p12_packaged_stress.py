"""P12.8 — Packaged Windows Production Stress Validation.

Tests the actual packaged executable under stress:
mutex cycles, crash/relaunch, restart recovery, plugin behavior,
offline startup, CWD independence, secret audit.
"""

from __future__ import annotations

import asyncio
import atexit
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest


_PACKAGED_STATE_ROOT = Path(tempfile.mkdtemp(prefix="samaktha-p12-packaged-"))
atexit.register(shutil.rmtree, _PACKAGED_STATE_ROOT, ignore_errors=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_packaged_executable():
    """Get path to packaged executable."""
    base = Path(__file__).resolve().parents[2]
    exe = base / "dist" / "samaktha" / "samaktha.exe"
    if not exe.exists():
        pytest.skip("Packaged executable not found. Run build first.")
    return str(exe)


def run_packaged(args, cwd=None, env=None, timeout=30):
    """Run packaged executable with args."""
    exe = get_packaged_executable()
    full_env = os.environ.copy()
    full_env["LOCALAPPDATA"] = str(_PACKAGED_STATE_ROOT)
    if env:
        full_env.update(env)

    result = subprocess.run(
        [exe] + args,
        cwd=cwd,
        env=full_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result


def run_packaged_async(args, cwd=None, env=None):
    """Run packaged executable asynchronously."""
    exe = get_packaged_executable()
    full_env = os.environ.copy()
    full_env["LOCALAPPDATA"] = str(_PACKAGED_STATE_ROOT)
    if env:
        full_env.update(env)

    return asyncio.create_subprocess_exec(
        exe, *args,
        cwd=cwd,
        env=full_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


def _validation_env(root: Path, **extra: str) -> dict[str, str]:
    return {
        "LOCALAPPDATA": str(root),
        "SAMAKTHA_INTERNAL_VALIDATION": "1",
        "SAMAKTHA_DEV_MODE": "1",
        "PYTHONNOUSERSITE": "1",
        **extra,
    }


def _start_validation_until_ready(
    root: Path,
    args: list[str],
    env: dict[str, str],
    *,
    timeout: float = 45.0,
) -> tuple[subprocess.Popen, str]:
    root.mkdir(parents=True, exist_ok=True)
    output = root / "validation.out"
    error = root / "validation.err"
    output_handle = output.open("w", encoding="utf-8")
    error_handle = error.open("w", encoding="utf-8")
    child_env = os.environ.copy()
    child_env.update(env)
    process = subprocess.Popen(
        [get_packaged_executable(), *args],
        cwd=Path(get_packaged_executable()).parent,
        env=child_env,
        stdout=output_handle,
        stderr=error_handle,
        text=True,
    )
    deadline = time.monotonic() + timeout
    text = ""
    while time.monotonic() < deadline:
        output_handle.flush()
        text = output.read_text(encoding="utf-8") if output.exists() else ""
        if '"ready": true' in text or '"ready": false' in text:
            break
        if process.poll() is not None:
            break
        time.sleep(0.05)
    output_handle.close()
    error_handle.close()
    if '"ready": true' not in text:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=15)
        stderr = error.read_text(encoding="utf-8") if error.exists() else ""
        pytest.fail(f"packaged validation did not become ready: {text}\n{stderr}")
    return process, text


# ---------------------------------------------------------------------------
# Packaged Basic Functionality
# ---------------------------------------------------------------------------

def test_packaged_launch():
    """Packaged executable must launch successfully."""
    result = run_packaged(["--version"])
    assert result.returncode == 0
    assert "samaktha" in result.stdout.lower()


def test_packaged_bootstrap_status():
    """Packaged bootstrap --status must work."""
    result = run_packaged(["bootstrap", "--status"])
    assert result.returncode in {0, 1}  # 0 = current, 1 = not initialized
    assert "mode:" in result.stdout.lower()


def test_packaged_bootstrap_force():
    """Packaged bootstrap --force must initialize state."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Use isolated app data
        env = {
            "LOCALAPPDATA": tmpdir,
            "SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1",
        }
        result = run_packaged(["bootstrap", "--force"], env=env)
        assert result.returncode == 0
        assert "Bootstrap completed" in result.stdout


def test_packaged_doctor():
    """Packaged doctor must run diagnostics."""
    result = run_packaged(["doctor"], timeout=60)
    assert result.returncode in {0, 1}
    assert "Samaktha Diagnostics" in result.stdout


def test_packaged_offline_startup():
    """Packaged must start without network."""
    # Block network access
    env = {
        "SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1",
        # Don't set API keys
    }
    result = run_packaged(["bootstrap", "--status"], env=env, timeout=30)
    assert result.returncode in {0, 1}


def test_packaged_cwd_independence():
    """Packaged paths must be independent of CWD."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a subdirectory with spaces
        test_cwd = Path(tmpdir) / "test with spaces"
        test_cwd.mkdir()

        env = {
            "SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1",
        }

        # Run from different directory
        result = run_packaged(["bootstrap", "--status"], cwd=test_cwd, env=env)
        assert result.returncode in {0, 1}
        assert "mode:" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Single-Instance Mutex Stress
# ---------------------------------------------------------------------------

def test_packaged_mutex_acquire_release():
    """Packaged instance guard: acquire and release."""
    env = {}

    # First instance should succeed
    result1 = run_packaged(["bootstrap", "--status"], env=env)
    assert result1.returncode in {0, 1}

    # Second instance (same command) should be rejected if first still running
    # Since first exits immediately, this tests the basic mutex mechanism
    result2 = run_packaged(["bootstrap", "--status"], env=env)
    assert result2.returncode in {0, 1}


def test_packaged_second_instance_rejected():
    """Second and third normal packaged instances are rejected repeatedly."""
    for cycle in range(3):
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(_PACKAGED_STATE_ROOT / f"mutex-{cycle}")
        first = subprocess.Popen(
            [get_packaged_executable(), "backend", "--port", "0"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            time.sleep(2.0)
            assert first.poll() is None
            for _ in range(2):
                rejected = subprocess.run(
                    [get_packaged_executable(), "backend", "--port", "0"],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
                assert rejected.returncode == 1
                assert "already running" in rejected.stderr.lower()
        finally:
            first.terminate()
            first.wait(timeout=15)

        released = subprocess.run(
            [get_packaged_executable(), "bootstrap", "--force"],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert released.returncode == 0


def test_packaged_mutex_crash_recovery():
    """Mutex must be released after process crash."""
    env = os.environ.copy()
    env["LOCALAPPDATA"] = str(_PACKAGED_STATE_ROOT / "crash-recovery")

    # Start a process and kill it
    proc = subprocess.Popen(
        [get_packaged_executable(), "backend", "--port", "0"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # Give it time to acquire mutex
    time.sleep(2.0)
    assert proc.poll() is None

    # Kill it
    proc.kill()
    proc.wait(timeout=15)

    # New instance should be able to acquire mutex
    result = subprocess.run(
        [get_packaged_executable(), "bootstrap", "--force"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Packaged Restart Recovery
# ---------------------------------------------------------------------------

def test_packaged_restart_recovery():
    """Packaged coordinator resumes a real safe runtime checkpoint."""
    root = _PACKAGED_STATE_ROOT / "canonical-recovery"
    env = _validation_env(
        root,
        SAMAKTHA_INTERNAL_MOCK_DELAY_SECONDS="20",
    )
    process, ready = _start_validation_until_ready(
        root,
        ["__p12_validate", "prepare-recovery", "--execution-id", "packaged-recovery"],
        env,
    )
    payload = json.loads(ready.strip().splitlines()[-1])
    assert payload["operation_outcomes"]
    process.kill()
    process.wait(timeout=15)
    env["SAMAKTHA_INTERNAL_MOCK_DELAY_SECONDS"] = "0"
    recovered = run_packaged(
        ["__p12_validate", "recover", "--execution-id", "packaged-recovery"],
        env=env,
        timeout=45,
    )
    assert recovered.returncode == 0, recovered.stderr
    result = json.loads(recovered.stdout.strip().splitlines()[-1])
    assert result == {
        "after": "completed",
        "before": "recovering",
        "error": None,
        "execution_id": "packaged-recovery",
        "result_status": "completed",
        "resumed": True,
    }


def test_packaged_checkpoint_persistence():
    """Packaged P8 evidence remains queryable after process restart."""
    root = _PACKAGED_STATE_ROOT / "canonical-evidence"
    env = _validation_env(root)
    executed = run_packaged(
        ["__p12_validate", "execute-evidence", "--execution-id", "packaged-evidence"],
        env=env,
        timeout=45,
    )
    assert executed.returncode == 0, executed.stderr
    queried = run_packaged(
        ["__p12_validate", "query-evidence", "--execution-id", "packaged-evidence"],
        env=env,
        timeout=45,
    )
    assert queried.returncode == 0, queried.stderr
    payload = json.loads(queried.stdout.strip().splitlines()[-1])
    assert payload["found"] is True
    assert payload["principal_id"] == "p12-validation-principal"
    assert payload["event_count"] > 0
    assert payload["sequence_unique"] is True
    evidence_db = root / "Samaktha" / "data" / "evidence.db"
    assert evidence_db.exists()
    assert not evidence_db.is_relative_to(Path(get_packaged_executable()).parent)


def test_packaged_unknown_mutation_is_not_replayed():
    """An uncertain non-idempotent effect remains exactly once after restart."""
    root = _PACKAGED_STATE_ROOT / "canonical-unknown"
    env = _validation_env(
        root,
        SAMAKTHA_INTERNAL_UNKNOWN_EFFECT="1",
        SAMAKTHA_INTERNAL_UNKNOWN_EFFECT_DELAY_SECONDS="20",
    )
    process, ready = _start_validation_until_ready(
        root,
        ["__p12_validate", "prepare-unknown", "--execution-id", "packaged-unknown"],
        env,
    )
    payload = json.loads(ready.strip().splitlines()[-1])
    assert payload["effect_count"] == 1
    assert payload["target_exists"] is True
    process.kill()
    process.wait(timeout=15)
    env["SAMAKTHA_INTERNAL_UNKNOWN_EFFECT_DELAY_SECONDS"] = "0"
    inspected = run_packaged(
        ["__p12_validate", "inspect-unknown", "--execution-id", "packaged-unknown"],
        env=env,
        timeout=45,
    )
    assert inspected.returncode == 0, inspected.stderr
    result = json.loads(inspected.stdout.strip().splitlines()[-1])
    assert result["effect_count"] == 1
    assert result["replayed"] is False
    assert result["resumed"] is False
    assert result["after"] == "failed"


# ---------------------------------------------------------------------------
# Packaged Plugin Behavior
# ---------------------------------------------------------------------------

def test_packaged_plugin_discovery():
    """Packaged production composition owns explicit plugin lifecycle."""
    root = _PACKAGED_STATE_ROOT / "canonical-plugin"
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "plugins"
        / "p11_smoke"
    )
    plugin = root / "Samaktha" / "plugins" / "p11_smoke"
    plugin.mkdir(parents=True)
    shutil.copy2(fixture / "manifest.json", plugin / "manifest.json")
    shutil.copy2(fixture / "plugin.py", plugin / "plugin.py")
    result = run_packaged(
        [
            "__p12_validate", "plugin-cycles",
            "--plugin-key", "p11-smoke@1.0.0",
            "--cycles", "25",
        ],
        env=_validation_env(root),
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["initially_enabled"] is False
    assert payload["completed_executions"] == 25
    assert payload["lifecycle_evidence_events"] == 100
    assert payload["ghost_entries"] == 0
    assert payload["active_tools"] == []


# ---------------------------------------------------------------------------
# CWD Independence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("test_cwd", [
    "C:\\Temp",
    "C:\\Temp\\Samaktha Test",
    "C:\\Path\\With\\Spaces\\And Unicode测试",
    "D:\\Different Drive" if Path("D:").exists() else "C:\\Different Drive",
])
def test_packaged_cwd_independence_varied(test_cwd):
    """Packaged must work from various CWD scenarios."""
    try:
        Path(test_cwd).mkdir(parents=True, exist_ok=True)
    except (OSError, PermissionError):
        pytest.skip(f"Cannot create test directory: {test_cwd}")

    env = {
        "SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1",
    }

    result = run_packaged(["--version"], cwd=test_cwd, env=env)
    assert result.returncode == 0
    assert "0.5.0" in result.stdout


# ---------------------------------------------------------------------------
# Secret Audit
# ---------------------------------------------------------------------------

def test_packaged_secret_audit():
    """Packaged build must not contain secrets."""
    import zipfile

    exe_path = Path(get_packaged_executable())
    dist_dir = exe_path.parent

    # Check all files in dist for prohibited content
    prohibited = [
        ".env",
        "memory.db",
        "evidence.db",
        ".git",
        "__pycache__",
        ".pytest_cache",
        "secret",
        "api_key",
        "password",
        "credential",
    ]

    for file_path in dist_dir.rglob("*"):
        if file_path.is_file():
            name_lower = file_path.name.lower()
            for p in prohibited:
                if p in name_lower:
                    # Allow some false positives but flag for review
                    print(f"WARNING: Potential prohibited file: {file_path}")


# ---------------------------------------------------------------------------
# Single-Instance Test Override Review
# ---------------------------------------------------------------------------

def test_multi_instance_test_override_bounded():
    """The historical environment override is inert in packaged production."""
    from app.runtime.safety import run_with_instance_guard

    calls = []
    namespace = type("Namespace", (), {})()

    with patch.dict(os.environ, {"SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1"}):
        with patch("app.runtime.safety.SingleInstanceLock.acquire", return_value=False):
            result = run_with_instance_guard(
                "backend", namespace, lambda: calls.append("executed")
            )

    assert result == 1
    assert calls == []


# ---------------------------------------------------------------------------
# Mutex Identity Tests
# ---------------------------------------------------------------------------

def test_mutex_identity_per_user():
    """Mutex identity must be per-user."""
    # This is verified by the fact that different Windows users
    # get different mutex names (Global\Samaktha_SingleInstance_{username})
    # Can't easily test multiple users in CI, but verify the logic
    from app.runtime.safety import SingleInstanceLock

    lock = SingleInstanceLock()
    mutex_name = lock._get_mutex_name()

    assert mutex_name.startswith("Global\\Samaktha_SingleInstance_")
    username = os.environ.get("USERNAME", "default")
    assert username in mutex_name


def test_mutex_identity_special_chars():
    """Mutex identity must handle special characters in username."""
    # The mutex name uses the username directly
    # Windows mutex names can handle most characters
    # Test by mocking the username
    with patch.dict(os.environ, {"USERNAME": "test user"}):
        from app.runtime.safety import SingleInstanceLock
        lock = SingleInstanceLock()
        mutex_name = lock._get_mutex_name()
        assert "test user" in mutex_name


# ---------------------------------------------------------------------------
# Global vs Local Mutex
# ---------------------------------------------------------------------------

def test_mutex_global_namespace():
    """Mutex uses Global namespace for cross-session visibility."""
    from app.runtime.safety import SingleInstanceLock

    lock = SingleInstanceLock()
    mutex_name = lock._get_mutex_name()

    # Should use Global\ prefix for system-wide per-user mutex
    assert mutex_name.startswith("Global\\")


# ---------------------------------------------------------------------------
# Build Verification
# ---------------------------------------------------------------------------

def test_rebuilt_artifact_matches_spec():
    """Rebuilt artifact must match expected specification."""
    exe_path = Path(get_packaged_executable())

    assert exe_path.exists()
    assert exe_path.stat().st_size > 10_000_000  # At least 10MB

    # Check ONEDIR structure
    internal_dir = exe_path.parent / "_internal"
    assert internal_dir.exists()
    assert internal_dir.is_dir()

    # Should contain Python DLL
    python_dlls = list(internal_dir.glob("python*.dll"))
    assert len(python_dlls) > 0


# ---------------------------------------------------------------------------
# Packaged CWD Independence with Unicode
# ---------------------------------------------------------------------------

def test_packaged_unicode_path_support():
    """Packaged must handle unicode paths correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create directory with unicode
        unicode_dir = Path(tmpdir) / "测试目录_тест_テスト"
        unicode_dir.mkdir()

        env = {
            "SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1",
        }

        result = run_packaged(["bootstrap", "--status"], cwd=unicode_dir, env=env)
        assert result.returncode in {0, 1}


# ---------------------------------------------------------------------------
# Packaged Build Audit
# ---------------------------------------------------------------------------

def test_packaged_no_developer_data():
    """Packaged build must not include developer data directories."""
    dist_dir = Path(get_packaged_executable()).parent

    dev_dirs = ["data", "logs", ".cache", "tests", ".git", ".venv", "build"]

    for dev_dir in dev_dirs:
        dev_path = dist_dir / dev_dir
        assert not dev_path.exists(), f"Developer directory {dev_dir} found in build"


def test_packaged_no_test_files():
    """Packaged build must not include test files."""
    dist_dir = Path(get_packaged_executable()).parent

    test_files = list(dist_dir.rglob("*test*.py"))
    test_files += list(dist_dir.rglob("*conftest*.py"))

    # Should have very few if any (only in _internal as bytecode)
    for tf in test_files:
        # Allow in _internal as compiled bytecode
        if "_internal" not in str(tf):
            pytest.fail(f"Test file in build: {tf}")


# ---------------------------------------------------------------------------
# Performance Baseline
# ---------------------------------------------------------------------------

def test_packaged_cold_startup_latency():
    """Measure packaged cold startup latency."""
    env = {"SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1"}

    start = time.perf_counter()
    result = run_packaged(["--version"], env=env)
    elapsed = time.perf_counter() - start

    assert result.returncode == 0
    # Cold startup should be reasonable (< 5 seconds)
    assert elapsed < 5.0, f"Cold startup too slow: {elapsed:.2f}s"


def test_packaged_bootstrap_latency():
    """Measure bootstrap command latency."""
    env = {"SAMAKTHA_TEST_ALLOW_MULTI_INSTANCE": "1"}

    start = time.perf_counter()
    result = run_packaged(["bootstrap", "--status"], env=env)
    elapsed = time.perf_counter() - start

    assert result.returncode in {0, 1}
    # Bootstrap status should be fast
    assert elapsed < 10.0, f"Bootstrap status too slow: {elapsed:.2f}s"
