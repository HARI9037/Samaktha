import logging
import traceback
from pathlib import Path

from app.fileparsers.base import DocumentParser, ParseResult
from app.fileparsers.ocr_parser import OCRParser
from app.fileparsers.pdf_parsers import DoclingParser, PdfPlumberParser, PyMuPDFParser
from app.fileparsers.text_parsers import MarkdownParser, TxtParser
from app.fileparsers.html_parser import HtmlParser
from app.fileparsers.office_parsers import DocxParser, PptxParser, XlsxParser

logger = logging.getLogger(__name__)

PDF_PARSERS = [PyMuPDFParser(), PdfPlumberParser(), OCRParser(), DoclingParser()]
TEXT_PARSERS = [MarkdownParser(), TxtParser()]
HTML_PARSERS = [HtmlParser()]
OFFICE_PARSERS = [DocxParser(), PptxParser(), XlsxParser()]

_ALL_PARSERS = PDF_PARSERS + TEXT_PARSERS + HTML_PARSERS + OFFICE_PARSERS


class DocumentParserFactory:
    @staticmethod
    def create(path: Path) -> DocumentParser:
        return DocumentParserChain(_ALL_PARSERS)

    @staticmethod
    def parse(path: Path) -> ParseResult:
        chain = DocumentParserChain(_ALL_PARSERS)
        return chain.parse(path)


class DocumentParserChain:
    def __init__(self, parsers: list[DocumentParser]) -> None:
        self._parsers = parsers

    def parse(self, path: Path) -> ParseResult:
        logger.info("DocumentParserChain: START parsing %s", path)
        best_error: str | None = None
        last_parser: str | None = None
        for parser in self._parsers:
            parser_name = parser.__class__.__name__
            try:
                can_handle = parser.can_handle(path)
            except Exception as e:
                logger.warning(
                    "[%s] can_handle(%s) raised %s: %s",
                    parser_name, path, type(e).__name__, e,
                )
                logger.debug("[%s] can_handle traceback:\n%s", parser_name, traceback.format_exc())
                continue

            if can_handle:
                last_parser = parser_name
                logger.info("Trying %s...", parser_name)
                try:
                    result = parser.parse(path)
                except Exception as e:
                    logger.warning(
                        "[%s] parse(%s) raised %s: %s",
                        parser_name, path, type(e).__name__, e,
                    )
                    logger.debug("[%s] parse traceback:\n%s", parser_name, traceback.format_exc())
                    logger.info("%s: FAIL", parser_name)
                    continue

                if result.ok:
                    stripped_len = len(result.text.strip())
                    images = result.metadata.get("images", 0)
                    tables = len(result.tables)

                    if not result.text.strip():
                        logger.info(
                            "%s: CONTINUE — text_stripped_len=0 images=%d tables=%d "
                            "metadata_parser=%s — no readable text, continuing to next parser",
                            parser_name, images, tables,
                            result.metadata.get("parser", parser_name),
                        )
                        continue

                    logger.info(
                        "%s: STOP — text_stripped_len=%d images=%d tables=%d "
                        "metadata_parser=%s — readable text found, returning SUCCESS",
                        parser_name, stripped_len, images, tables,
                        result.metadata.get("parser", parser_name),
                    )
                    return result

                logger.warning(
                    "%s: FAIL — %s",
                    parser_name, result.error,
                )
                if result.error and (
                    best_error is None
                    or result.metadata.get("ocr_used") is not None
                ):
                    best_error = result.error
                continue

        logger.warning("DocumentParserChain: ALL PARSERS EXHAUSTED for %s", path)
        final_error = (
            best_error
            or (
                f"Parser chain exhausted. Final parser: {last_parser}. See opencode_debug.log"
                if last_parser
                else "Parser chain exhausted. No parser selected."
            )
        )
        return ParseResult(
            ok=False,
            error=final_error,
        )