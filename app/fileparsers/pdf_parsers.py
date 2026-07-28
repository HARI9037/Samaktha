import logging
import traceback
from pathlib import Path

from app.fileparsers.base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)


class PyMuPDFParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            import fitz
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("PyMuPDFParser: START path=%s", path)
        try:
            import fitz
        except ImportError as e:
            logger.warning("PyMuPDFParser: fitz not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="PyMuPDF is not installed.")

        doc = None
        try:
            logger.debug("PyMuPDFParser: calling fitz.open(%s)", path)
            doc = fitz.open(str(path))
            logger.debug("PyMuPDFParser: fitz.open succeeded, pages=%s", doc.page_count)
        except Exception as e:
            logger.warning("PyMuPDFParser: fitz.open(%s) raised %s: %s\n%s", path, type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="PyMuPDF could not open the document.")

        try:
            title = path.stem
            page_count = doc.page_count
            text_parts = []
            tables = []
            total_images = 0

            for page_idx in range(page_count):
                logger.debug("PyMuPDFParser: processing page %d/%d", page_idx + 1, page_count)
                try:
                    page = doc[page_idx]
                    page_text = page.get_text()
                    text_parts.append(page_text)
                    logger.debug(
                        "PyMuPDFParser: page %d get_text() length=%d raw=%s",
                        page_idx, len(page_text), repr(page_text[:100]),
                    )
                except Exception as e:
                    logger.warning("PyMuPDFParser: page %d get_text raised %s: %s", page_idx, type(e).__name__, e)
                    text_parts.append("")
                    continue

                try:
                    tabs = page.find_tables()
                    tab_count = 0
                    try:
                        tab_count = len(tabs) if hasattr(tabs, '__len__') else 0
                    except Exception:
                        tab_count = 0
                    if tab_count > 0:
                        logger.debug("PyMuPDFParser: found %d tables on page %d", tab_count, page_idx)
                        for tab in tabs:
                            try:
                                row_data = tab.extract()
                                tables.append(row_data)
                            except Exception as e:
                                logger.warning("PyMuPDFParser: table extraction failed on page %d: %s", page_idx, e)
                except Exception as e:
                    logger.warning("PyMuPDFParser: find_tables failed on page %d: %s", page_idx, e)

                try:
                    image_list = page.get_images()
                    page_images = len(image_list) if image_list else 0
                    total_images += page_images
                except Exception:
                    pass

            text = "\n".join(text_parts).strip()
            table_count = len(tables)

            logger.info(
                "PyMuPDFParser: EXTRACT — text_len=%d text_stripped_len=%d pages=%d tables=%d images=%d",
                len(text), len(text.strip()), page_count, table_count, total_images,
            )

            if text:
                logger.info(
                    "PyMuPDFParser: DECISION — text_len=%d >= 1, returning SUCCESS (no OCR needed)",
                    len(text),
                )
            else:
                logger.info(
                    "PyMuPDFParser: DECISION — text is empty after strip, continuing to next parser for OCR "
                    "(pages=%d images=%d tables=%d)",
                    page_count, total_images, table_count,
                )

            return ParseResult(
                ok=True,
                text=text,
                title=title,
                page_count=page_count,
                tables=tables,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": ".pdf",
                    "parser": "pymupdf",
                    "images": total_images,
                    "scanned_pdf": not bool(text),
                },
            )
        except Exception as e:
            logger.warning("PyMuPDFParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="PyMuPDF parsing failed.")
        finally:
            try:
                doc.close()
                logger.debug("PyMuPDFParser: doc closed")
            except Exception as e:
                logger.warning("PyMuPDFParser: doc.close failed: %s", e)


class DoclingParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._is_available()
        if suffix in (".docx", ".pptx", ".xlsx"):
            return self._is_available()
        return False

    def _is_available(self) -> bool:
        try:
            import docling
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("DoclingParser: START path=%s", path)
        try:
            from docling.document_converter import DocumentConverter
        except ImportError as e:
            logger.warning("DoclingParser: docling not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="Docling is not installed.")

        try:
            converter = DocumentConverter()
            result = converter.convert(str(path))
            doc = result.document
        except Exception as e:
            logger.warning("DoclingParser: convert(%s) raised %s: %s\n%s", path, type(e).__name__, e, traceback.format_exc())
            return ParseResult(
                ok=False,
                error="Unable to load advanced document parser. Falling back to basic parser.",
            )

        try:
            title = path.stem
            if doc.name and doc.name != path.stem:
                title = doc.name

            try:
                page_count = doc.num_pages()
            except Exception as e:
                logger.warning("DoclingParser: num_pages() raised %s: %s", type(e).__name__, e)
                page_count = 0

            sections = []
            if hasattr(doc, "field_regions") and doc.field_regions:
                for fr in doc.field_regions:
                    sections.append(str(fr))

            tables = []
            if hasattr(doc, "tables") and doc.tables:
                for i, table in enumerate(doc.tables):
                    try:
                        tables.append({"index": i, "text": table.export_to_markdown()})
                    except Exception as e:
                        logger.warning("DoclingParser: table %d export raised %s: %s", i, type(e).__name__, e)
                        tables.append({"index": i, "text": str(table)})

            images = []
            if hasattr(doc, "pictures") and doc.pictures:
                for i, pic in enumerate(doc.pictures):
                    images.append({"index": i, "caption": str(pic)})

            try:
                text_content = doc.export_to_markdown()
            except Exception as e:
                logger.warning("DoclingParser: export_to_markdown raised %s: %s, trying export_to_text", type(e).__name__, e)
                try:
                    text_content = doc.export_to_text()
                except Exception as e2:
                    logger.warning("DoclingParser: export_to_text also raised %s: %s", type(e2).__name__, e2)
                    text_content = ""

            logger.info("DoclingParser: SUCCESS — text_len=%d, pages=%d", len(text_content), page_count)
            return ParseResult(
                ok=True,
                text=text_content,
                title=title,
                page_count=page_count,
                tables=tables,
                sections=sections,
                images=images,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "docling",
                },
            )
        except Exception as e:
            logger.warning("DoclingParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="Docling parsing failed.")


class PdfPlumberParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        if path.suffix.lower() != ".pdf":
            return False
        try:
            import pdfplumber
            return True
        except Exception:
            return False

    def parse(self, path: Path) -> ParseResult:
        logger.info("PdfPlumberParser: START path=%s", path)
        try:
            import pdfplumber
        except ImportError as e:
            logger.warning("PdfPlumberParser: pdfplumber not installed — %s: %s", type(e).__name__, e)
            return ParseResult(ok=False, error="pdfplumber is not installed.")

        try:
            text_parts = []
            tables = []
            page_count = 0

            logger.debug("PdfPlumberParser: calling pdfplumber.open(%s)", path)
            with pdfplumber.open(str(path)) as pdf:
                pages = pdf.pages
                page_count = len(pages)
                logger.debug("PdfPlumberParser: opened, pages=%d", page_count)

                for page_idx, page in enumerate(pages):
                    logger.debug("PdfPlumberParser: processing page %d/%d", page_idx + 1, page_count)
                    try:
                        text = page.extract_text()
                        logger.debug("PdfPlumberParser: page %d extract_text() length=%d", page_idx, len(text or ""))
                        if text:
                            text_parts.append(text)
                    except Exception as e:
                        logger.warning("PdfPlumberParser: page %d extract_text raised %s: %s", page_idx, type(e).__name__, e)

                    try:
                        page_tables = page.extract_tables()
                        if page_tables:
                            logger.debug("PdfPlumberParser: found %d tables on page %d", len(page_tables), page_idx)
                            for tab in page_tables:
                                tables.append(tab)
                    except Exception as e:
                        logger.warning("PdfPlumberParser: page %d extract_tables raised %s: %s", page_idx, type(e).__name__, e)

            text = "\n".join(text_parts).strip()
            logger.info("PdfPlumberParser: SUCCESS — text_len=%d, pages=%d, tables=%d",
                        len(text), page_count, len(tables))

            return ParseResult(
                ok=True,
                text=text,
                title=path.stem,
                page_count=page_count,
                tables=tables,
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": ".pdf",
                    "parser": "pdfplumber",
                },
            )
        except Exception as e:
            logger.warning("PdfPlumberParser: parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            return ParseResult(ok=False, error="pdfplumber parsing failed.")