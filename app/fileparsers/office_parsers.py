import logging
import traceback
from pathlib import Path

from app.fileparsers.base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class DocxParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".docx":
            return False
        return self._is_available()

    def _is_available(self) -> bool:
        try:
            import docling
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("DocxParser: START path=%s", path)
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            logger.warning("DocxParser: docling not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="Docling is not installed.")

        try:
            converter = DocumentConverter()
            result = converter.convert(str(path))
            doc = result.document
        except Exception as e:
            logger.warning("DocxParser: convert(%s) raised %s: %s\n%s", path, type(e).__name__, e, traceback.format_exc())
            return ParseResult(
                ok=False,
                error="Unable to load advanced document parser. Falling back to basic parser.",
            )

        try:
            try:
                text_content = doc.export_to_markdown()
            except Exception as e:
                logger.warning("DocxParser: export_to_markdown raised %s: %s, trying export_to_text", type(e).__name__, e)
                try:
                    text_content = doc.export_to_text()
                except Exception as e2:
                    logger.warning("DocxParser: export_to_text raised %s: %s", type(e2).__name__, e2)
                    text_content = ""

            try:
                page_count = doc.num_pages()
            except Exception as e:
                logger.warning("DocxParser: num_pages raised %s: %s", type(e).__name__, e)
                page_count = 0

            logger.info("DocxParser: SUCCESS — text_len=%d", len(text_content))
            return ParseResult(
                ok=True,
                text=text_content,
                title=path.stem,
                page_count=page_count,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "docling",
                },
            )
        except Exception as e:
            logger.warning("DocxParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="Docling parsing failed.")


class PptxParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".pptx":
            return False
        return self._is_available()

    def _is_available(self) -> bool:
        try:
            import docling
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("PptxParser: START path=%s", path)
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            logger.warning("PptxParser: docling not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="Docling is not installed.")

        try:
            converter = DocumentConverter()
            result = converter.convert(str(path))
            doc = result.document
        except Exception as e:
            logger.warning("PptxParser: convert(%s) raised %s: %s\n%s", path, type(e).__name__, e, traceback.format_exc())
            return ParseResult(
                ok=False,
                error="Unable to load advanced document parser. Falling back to basic parser.",
            )

        try:
            try:
                text_content = doc.export_to_markdown()
            except Exception as e:
                logger.warning("PptxParser: export_to_markdown raised %s: %s, trying export_to_text", type(e).__name__, e)
                try:
                    text_content = doc.export_to_text()
                except Exception as e2:
                    logger.warning("PptxParser: export_to_text raised %s: %s", type(e2).__name__, e2)
                    text_content = ""

            try:
                page_count = doc.num_pages()
            except Exception as e:
                logger.warning("PptxParser: num_pages raised %s: %s", type(e).__name__, e)
                page_count = 0

            logger.info("PptxParser: SUCCESS — text_len=%d", len(text_content))
            return ParseResult(
                ok=True,
                text=text_content,
                title=path.stem,
                page_count=page_count,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "docling",
                },
            )
        except Exception as e:
            logger.warning("PptxParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="Docling parsing failed.")


class XlsxParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".xlsx":
            return False
        return self._is_available()

    def _is_available(self) -> bool:
        try:
            import docling
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("XlsxParser: START path=%s", path)
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            logger.warning("XlsxParser: docling not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="Docling is not installed.")

        try:
            converter = DocumentConverter()
            result = converter.convert(str(path))
            doc = result.document
        except Exception as e:
            logger.warning("XlsxParser: convert(%s) raised %s: %s\n%s", path, type(e).__name__, e, traceback.format_exc())
            return ParseResult(
                ok=False,
                error="Unable to load advanced document parser. Falling back to basic parser.",
            )

        try:
            try:
                text_content = doc.export_to_markdown()
            except Exception as e:
                logger.warning("XlsxParser: export_to_markdown raised %s: %s, trying export_to_text", type(e).__name__, e)
                try:
                    text_content = doc.export_to_text()
                except Exception as e2:
                    logger.warning("XlsxParser: export_to_text raised %s: %s", type(e2).__name__, e2)
                    text_content = ""

            try:
                page_count = doc.num_pages()
            except Exception as e:
                logger.warning("XlsxParser: num_pages raised %s: %s", type(e).__name__, e)
                page_count = 0

            logger.info("XlsxParser: SUCCESS — text_len=%d", len(text_content))
            return ParseResult(
                ok=True,
                text=text_content,
                title=path.stem,
                page_count=page_count,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "docling",
                },
            )
        except Exception as e:
            logger.warning("XlsxParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="Docling parsing failed.")