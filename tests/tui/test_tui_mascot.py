"""Tests for Samaktha TUI Mascot Widget."""

import os
from pathlib import Path

from app.tui.mascot import MASCOT_PATH, MascotWidget, _build_mascot_renderable


def test_mascot_asset_exists():
    """The mascot PNG must be present in the assets directory."""
    assert MASCOT_PATH.exists(), (
        f"Mascot asset missing at {MASCOT_PATH}. "
        "Run the Phase 6.2 setup to install the asset."
    )


def test_mascot_asset_is_image():
    """The asset must be a non-empty file."""
    assert MASCOT_PATH.stat().st_size > 0


def test_mascot_renderable_returns_string():
    """_build_mascot_renderable must always return a string (never raises)."""
    result = _build_mascot_renderable()
    assert isinstance(result, str)
    assert len(result) > 0


def test_mascot_widget_class_exists():
    """MascotWidget must be importable and be a class."""
    assert MascotWidget is not None
    assert hasattr(MascotWidget, "render")


def test_mascot_path_is_under_tui_assets():
    """Asset must live inside app/tui/assets — not in runtime directories."""
    assert "tui" in str(MASCOT_PATH)
    assert "assets" in str(MASCOT_PATH)
