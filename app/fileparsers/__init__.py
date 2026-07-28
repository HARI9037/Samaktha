from app.fileparsers.base import DocumentParser, ParseResult
from app.fileparsers.factory import DocumentParserFactory, DocumentParserChain
from app.fileparsers.ocr_parser import OCRParser
from app.fileparsers.pdf_parsers import DoclingParser, PdfPlumberParser, PyMuPDFParser
from app.fileparsers.text_parsers import MarkdownParser, TxtParser
from app.fileparsers.html_parser import HtmlParser
from app.fileparsers.office_parsers import DocxParser, PptxParser, XlsxParser