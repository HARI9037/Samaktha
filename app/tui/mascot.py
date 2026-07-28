"""Presentation-only mascot rendering for Samaktha.

The PNG is the source of truth. Pillow is used when available to translate
the asset into ANSI color blocks; the deterministic sprite keeps the identity
visible in minimal environments where Pillow is not installed.
"""

from __future__ import annotations

from pathlib import Path

from textual.widgets import Static

MASCOT_PATH = Path(__file__).parent / "assets" / "mascot.png"

_MASCOT_ASCII = """[bold #FF8C00]      ▄▄[/]
[bold #FFB300]   ▄██████▄[/]
[bold #FF8C00] ▄██████████▄[/]
[bold #FFB300] ███[white]●[/]████[white]●[/]███[/]
[bold #FF8C00] █████[red]⌣[/]█████[/]
[bold #FFB300]  ▀████████▀[/]
[bold #FF8C00]    ██  ██[/]"""


def _build_mascot_renderable() -> str:
    """Return an ANSI rendering derived from the official mascot asset."""
    if not MASCOT_PATH.exists():
        return _MASCOT_ASCII

    try:
        from PIL import Image

        image = Image.open(MASCOT_PATH).convert("RGB")
        thumb = image.resize((12, 7), Image.Resampling.LANCZOS)
        pixels = list(thumb.getdata())
        rows: list[str] = []
        for y in range(7):
            row: list[str] = []
            for x in range(12):
                r, g, b = pixels[y * 12 + x]
                if r > 235 and g > 235 and b > 235:
                    row.append(" ")
                else:
                    row.append(f"[rgb({r},{g},{b})]█[/]")
            rows.append("".join(row))
        return "\n".join(rows)
    except Exception:
        return _MASCOT_ASCII


class MascotWidget(Static):
    """Compact mascot with extension points for future visual states."""

    DEFAULT_CSS = """
    MascotWidget {
        width: 14;
        height: 7;
        content-align: left middle;
    }
    """

    def render(self) -> str:  # type: ignore[override]
        return _build_mascot_renderable()
