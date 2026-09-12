"""Core imports and basic file processing must not load experimental ML DLLs."""
import ast
from pathlib import Path
import subprocess
import sys
import tomllib

from app.fileparsers.factory import DocumentParserFactory
from app.fileparsers.writer import write_document


def test_core_imports_do_not_load_native_ml_stack():
    code = "import sys; import app.cli, app.core.app, app.tui.app, app.setup.wizard; assert not any(k.split('.')[0] in {'torch','docling','transformers','faster_whisper','openwakeword'} for k in sys.modules)"
    result = subprocess.run([sys.executable, "-B", "-c", code], capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert "access violation" not in result.stderr.lower()


def test_direct_core_dependencies_declared():
    metadata = tomllib.loads(Path("pyproject.toml").read_text())
    deps = "\n".join(metadata["project"]["dependencies"]).lower()
    for name in ("textual", "httpx", "pymupdf", "pdfplumber", "pypdf", "python-docx", "openpyxl", "pyperclip", "beautifulsoup4", "pillow", "pywin32", "pystray", "keyboard", "windows-toasts", "ddgs", "pydantic", "fastapi", "uvicorn"):
        assert any(dep.startswith(name) for dep in deps.splitlines()), name


def test_basic_office_roundtrip_has_no_docling_dependency(tmp_path):
    for suffix in (".docx", ".xlsx"):
        path = tmp_path / ("roundtrip" + suffix)
        write_document(path, "Samaktha pilot test.")
        result = DocumentParserFactory.parse(path)
        assert result.ok
        assert "Samaktha pilot test." in result.text
        assert result.metadata["parser"] == "basic_office"


def test_blank_and_corrupt_pdf_do_not_activate_docling(tmp_path, monkeypatch):
    import builtins
    import fitz
    original = builtins.__import__
    attempted = []
    def guarded(name, *args, **kwargs):
        if name.split(".")[0] in {"docling", "torch", "transformers"}:
            attempted.append(name)
            raise AssertionError("Core PDF fallback attempted experimental ML import")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", guarded)
    blank = tmp_path / "blank.pdf"
    document = fitz.open()
    document.new_page()
    document.save(blank)
    document.close()
    corrupt = tmp_path / "corrupt.pdf"
    corrupt.write_bytes(b"invalid PDF")
    assert not DocumentParserFactory.parse(blank).ok
    assert not DocumentParserFactory.parse(corrupt).ok
    assert not attempted
