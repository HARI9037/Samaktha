"""Regression tests for OCR pipeline.

Tests the full parser chain with OCR fallback for scanned PDFs.
"""
import os
import tempfile
from pathlib import Path

import pytest
from app.fileparsers.base import ParseResult
from app.fileparsers.factory import DocumentParserFactory


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def text_pdf() -> Path:
    """A PDF with real extractable text."""
    import fitz
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_text_{os.urandom(4).hex()}.pdf")
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "Hello World, this is a text PDF.", fontsize=12)
    page.insert_text((50, 140), "Line two with more content.", fontsize=12)
    doc.save(tmp)
    doc.close()
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


@pytest.fixture(scope="session")
def multi_page_text_pdf() -> Path:
    """A multi-page PDF with text."""
    import fitz
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_multi_{os.urandom(4).hex()}.pdf")
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((50, 100), f"Page {i+1} content.", fontsize=12)
    doc.save(tmp)
    doc.close()
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


@pytest.fixture(scope="session")
def scanned_pdf() -> Path:
    """A PDF with only an image (no text layer) — truly scanned."""
    from PIL import Image
    import fitz
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_scanned_{os.urandom(4).hex()}.pdf")
    img_path = tmp + ".png"
    img = Image.new("RGB", (400, 100), color="white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "SCANNED DOCUMENT", fill="black")
    draw.text((20, 50), "Page 1 of report", fill="black")
    img.save(img_path)
    doc = fitz.open()
    page = doc.new_page()
    page.insert_image(page.rect, filename=img_path)
    doc.save(tmp)
    doc.close()
    try:
        os.unlink(img_path)
    except PermissionError:
        pass
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


@pytest.fixture(scope="session")
def corrupted_pdf() -> Path:
    """An invalid/corrupted PDF file."""
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_corrupt_{os.urandom(4).hex()}.pdf")
    with open(tmp, "wb") as f:
        f.write(b"%PDF-1.4\n%corrupted\n0 0 obj\nendobj\n%%%%EOF\n")
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


@pytest.fixture(scope="session")
def image_only_file() -> Path:
    """A PNG image file (treated as image-only document)."""
    from PIL import Image
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_img_{os.urandom(4).hex()}.png")
    img = Image.new("RGB", (200, 60), color="white")
    from PIL import ImageDraw
    draw = ImageDraw.Draw(img)
    draw.text((10, 20), "Image file content", fill="black")
    img.save(tmp)
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


@pytest.fixture(scope="session")
def empty_text_pdf() -> Path:
    """A PDF with empty extractable text (simulates scanned-like but with text layer)."""
    import fitz
    tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_empty_{os.urandom(4).hex()}.pdf")
    doc = fitz.open()
    doc.new_page()
    doc.save(tmp)
    doc.close()
    yield Path(tmp)
    try:
        os.unlink(tmp)
    except PermissionError:
        pass


# ── Helper ─────────────────────────────────────────────────────────

def _chain_parse(path: Path) -> ParseResult:
    return DocumentParserFactory.parse(path)


# ── Tests ──────────────────────────────────────────────────────────

class TestTextPDF:
    """Text PDFs should skip OCR and be handled by PyMuPDFParser."""

    def test_extracts_text(self, text_pdf):
        result = _chain_parse(text_pdf)
        assert result.ok is True
        assert "Hello World" in result.text
        assert result.metadata.get("scanned_pdf") is False
        assert result.metadata.get("parser") == "pymupdf"

    def test_multi_page(self, multi_page_text_pdf):
        result = _chain_parse(multi_page_text_pdf)
        assert result.ok is True
        assert "Page 1" in result.text
        assert "Page 3" in result.text
        assert result.page_count == 3

    def test_parser_is_pymupdf_not_ocr(self, text_pdf):
        result = _chain_parse(text_pdf)
        assert result.metadata.get("parser") == "pymupdf"
        assert result.metadata.get("ocr_used") is None


class TestScannedPDF:
    """Scanned PDFs should trigger OCR automatically."""

    def test_ocr_triggered(self, scanned_pdf):
        result = _chain_parse(scanned_pdf)
        assert result.ok is True
        assert result.metadata.get("scanned_pdf") is True
        assert result.metadata.get("ocr_used") is not None

    def test_ocr_extracts_text(self, scanned_pdf):
        result = _chain_parse(scanned_pdf)
        assert result.ok is True
        if result.text.strip():
            assert "SCANNED" in result.text or "DOCUMENT" in result.text or "Page" in result.text

    def test_metadata_preserved(self, scanned_pdf):
        result = _chain_parse(scanned_pdf)
        assert result.metadata.get("parser") == "ocr"
        assert result.metadata.get("scanned_pdf") is True
        assert result.metadata.get("source_path") == str(scanned_pdf)
        assert result.metadata.get("page_count", result.page_count) >= 1


class TestImageOnlyDocument:
    """Image-only files (PNG, JPG) should also go through OCR."""

    def test_image_file_ocr(self, image_only_file):
        result = _chain_parse(image_only_file)
        assert result.ok is True
        assert result.metadata.get("scanned_pdf") is True
        assert result.metadata.get("ocr_used") is not None
        assert result.metadata.get("parser") == "ocr"


class TestCorruptedPDF:
    """Corrupted PDFs should fail gracefully."""

    def test_corrupted_returns_error(self, corrupted_pdf):
        result = _chain_parse(corrupted_pdf)
        assert result.ok is False
        assert result.error is not None


class TestEmptyTextPDF:
    """PDF with no text but not scanned (blank) should not crash."""

    def test_blank_pdf(self, empty_text_pdf):
        result = _chain_parse(empty_text_pdf)
        # Blank PDFs with no content at all may fail OCR too
        assert result.ok is False
        assert "no readable text" in (result.error or "")


class TestParserChainOrder:
    """Verify the parser chain has the correct order."""

    def test_pymupdf_is_first(self):
        from app.fileparsers.factory import PDF_PARSERS
        names = [p.__class__.__name__ for p in PDF_PARSERS]
        assert names == ["PyMuPDFParser", "PdfPlumberParser", "OCRParser", "DoclingParser"]


class TestOCRParserDirect:
    """Direct tests for OCRParser."""

    def test_can_handle_pdf(self):
        from app.fileparsers.ocr_parser import OCRParser
        parser = OCRParser()
        assert parser.can_handle(Path("test.pdf")) is True
        assert parser.can_handle(Path("test.png")) is True
        assert parser.can_handle(Path("test.jpg")) is True
        assert parser.can_handle(Path("test.jpeg")) is True
        assert parser.can_handle(Path("test.txt")) is False

    def test_easyocr_available(self):
        from app.fileparsers.ocr_parser import OCRParser
        parser = OCRParser()
        available = parser._is_easyocr_available()
        assert isinstance(available, bool)

    def test_error_on_missing_ocr(self):
        from app.fileparsers.ocr_parser import OCRParser
        parser = OCRParser()
        original_easyocr = parser._is_easyocr_available
        original_tesseract = parser._is_tesseract_available
        parser._is_easyocr_available = lambda: False
        parser._is_tesseract_available = lambda: False
        try:
            result = parser.parse(Path("nonexistent.pdf"))
            assert result.ok is False
            assert "no readable text" in (result.error or "")
        finally:
            parser._is_easyocr_available = original_easyocr
            parser._is_tesseract_available = original_tesseract


class TestContextBuilderFormatting:
    """ContextBuilder must never mention OCR/parsers to the LLM."""

    def test_document_content_format_no_ocr_mention(self):
        from app.core.context_builder import ContextBuilder
        cb = ContextBuilder()
        output = cb._format_output({
            "path": "nor.pdf",
            "result": {
                "title": "nor",
                "page_count": 3,
                "text": "NOR gate truth table...",
                "metadata": {"ocr_used": "easyocr", "parser": "ocr", "scanned_pdf": True},
            },
        })
        assert "[DOCUMENT CONTENT" in output
        assert "OCR" not in output
        assert "easyocr" not in output
        assert "scanned" not in output
        assert "parser" not in output
        assert "NOR gate truth table" in output

    def test_document_content_empty_text(self):
        from app.core.context_builder import ContextBuilder
        cb = ContextBuilder()
        output = cb._format_output({
            "path": "blank.pdf",
            "result": {
                "title": "blank",
                "page_count": 1,
                "text": "",
                "metadata": {},
            },
        })
        assert "[DOCUMENT CONTENT" in output
        assert "No text content extracted" in output
        assert "OCR" not in output


class TestDocumentToolExtensions:
    """DocumentTool must handle image files via DOCUMENT_EXTENSIONS."""

    def test_image_extensions_included(self):
        from app.tools.document import DOCUMENT_EXTENSIONS
        assert ".png" in DOCUMENT_EXTENSIONS
        assert ".jpg" in DOCUMENT_EXTENSIONS
        assert ".jpeg" in DOCUMENT_EXTENSIONS
        assert ".tiff" in DOCUMENT_EXTENSIONS


class TestOCRCaching:
    """OCR results should be cached and reused."""

    def test_cache_key_uses_timestamp(self):
        from app.fileparsers.ocr_parser import OCRParser
        import tempfile
        parser = OCRParser()
        tmp = os.path.join(tempfile.gettempdir(), f"ocr_test_cache_{os.urandom(4).hex()}.pdf")
        try:
            with open(tmp, "wb") as f:
                f.write(b"%PDF-1.4 dummy")
            key1 = parser._cache_key(Path(tmp))
            key2 = parser._cache_key(Path(tmp))
            assert key1 == key2
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def test_cache_directory_created(self):
        from app.fileparsers.ocr_parser import _CACHE_DIR
        assert _CACHE_DIR.name == "samaktha_ocr_cache"
