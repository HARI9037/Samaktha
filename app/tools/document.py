import logging
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from app.fileparsers.base import ParseResult
from app.fileparsers.factory import DocumentParserFactory, DocumentParserChain, _ALL_PARSERS
from app.tools.base import Tool, ToolResult
from app.tools.resolver import FileResolver, MultipleMatches

logger = logging.getLogger(__name__)

DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".markdown", ".html", ".htm",
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
}


def is_document_file(path: Path) -> bool:
    return path.suffix.lower() in DOCUMENT_EXTENSIONS


class DocumentResult:
    def __init__(
        self,
        title: Optional[str] = None,
        page_count: int = 0,
        sections: Optional[list] = None,
        tables: Optional[list] = None,
        images: Optional[list] = None,
        text: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.title = title
        self.page_count = page_count
        self.sections = sections or []
        self.tables = tables or []
        self.images = images or []
        self.text = text
        self.metadata = metadata or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "page_count": self.page_count,
            "sections": self.sections,
            "tables": self.tables,
            "images": self.images,
            "text": self.text,
            "metadata": self.metadata,
        }


class DocumentTool(Tool):
    def __init__(self, root_dir: str | Path | None = None) -> None:
        self._resolver = FileResolver(root_dir)
        self._factory = DocumentParserFactory()

    @property
    def name(self) -> str:
        return "document"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "read_document")
        path_str = arguments.get("path") or arguments.get("target_path")

        logger.info("DocumentTool: ENTER — action=%s path=%s", action, path_str)

        if not path_str:
            return ToolResult(ok=False, error="Missing required argument 'path'")

        logger.debug("DocumentTool.run: action=%s, path_str=%s", action, path_str)

        resolved = self._resolver.resolve(path_str)
        if isinstance(resolved, MultipleMatches):
            return ToolResult(
                ok=False,
                error="MULTIPLE_MATCHES",
                data={"candidates": resolved.candidates},
            )
        if resolved is None:
            return ToolResult(ok=False, error="Resource not found.")
        target_path = resolved

        logger.debug("DocumentTool.run: resolved to %s", target_path)

        if not target_path.exists():
            return ToolResult(ok=False, error=f"Document does not exist: {target_path}")

        if not target_path.is_file():
            return ToolResult(ok=False, error="Target is not a file.")

        if not is_document_file(target_path):
            return ToolResult(ok=False, error=f"Unsupported file format: {target_path.suffix}")

        try:
            if action in ("read_document", "read", "extract_text"):
                logger.debug("DocumentTool.run: calling _read_document")
                result = await self._read_document(target_path)
            elif action == "summarize_document":
                result = await self._summarize_document(target_path)
            elif action == "extract_tables":
                result = await self._extract_tables(target_path)
            elif action == "extract_metadata":
                result = await self._extract_metadata(target_path)
            else:
                result = ToolResult(ok=False, error=f"Unsupported document action: {action}")
            logger.info("DocumentTool: EXIT — ok=%s error=%s data_keys=%s", result.ok, result.error, list(result.data.keys()) if result.ok else [])
            return result
        except Exception as e:
            tb = traceback.format_exc()
            logger.warning(
                "DocumentTool EXCEPTION:\n"
                "  file: %s\n"
                "  action: %s\n"
                "  type: %s\n"
                "  message: %s\n"
                "  traceback:\n%s",
                target_path, action, type(e).__name__, e, tb,
            )
            return ToolResult(ok=False, error=f"[DocumentTool] {type(e).__name__}: {e}")

    async def _read_document(self, path: Path) -> ToolResult:
        logger.debug("_read_document: path=%s, suffix=%s", path, path.suffix.lower())
        if path.suffix.lower() == ".pdf":
            result = self._read_pdf(path)
            logger.debug("_read_document: _read_pdf returned ok=%s", result.ok)
            return result

        logger.debug("_read_document: delegating to factory.parse")
        try:
            parse_result = self._factory.parse(path)
        except Exception as e:
            logger.warning("_read_document: factory.parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            raise

        if not parse_result.ok:
            logger.warning("_read_document: factory.parse failed: %s", parse_result.error)
            return ToolResult(ok=False, error=parse_result.error or "Document could not be parsed.")
        return self._build_result(path, parse_result)

    def _read_pdf(self, path: Path) -> ToolResult:
        logger.debug("_read_pdf: path=%s", path)
        try:
            parse_result = self._factory.parse(path)
        except Exception as e:
            logger.warning("_read_pdf: factory.parse raised %s: %s\n%s", type(e).__name__, e, traceback.format_exc())
            raise

        logger.debug("_read_pdf: factory.parse returned ok=%s, error=%s", parse_result.ok, parse_result.error)

        if not parse_result.ok:
            logger.warning("_read_pdf: factory.parse failed: %s", parse_result.error)
            return ToolResult(ok=False, error=parse_result.error or "Document could not be parsed.")

        logger.debug("_read_pdf: factory.parse ok, calling _build_result")
        return self._build_result(path, parse_result)

    async def _summarize_document(self, path: Path) -> ToolResult:
        read_result = await self._read_document(path)
        if not read_result.ok:
            return read_result

        doc_result = read_result.data.get("result", {})
        text = doc_result.get("text", "")

        if len(text) > 10000:
            text = text[:10000] + "\n\n[... truncated ...]"

        return ToolResult(
            ok=True,
            data={
                "path": str(path),
                "title": doc_result.get("title"),
                "text": text,
                "page_count": doc_result.get("page_count"),
                "summary_ready": True,
            },
        )

    async def _extract_tables(self, path: Path) -> ToolResult:
        read_result = await self._read_document(path)
        if not read_result.ok:
            return read_result

        doc_result = read_result.data.get("result", {})
        tables = doc_result.get("tables", [])

        return ToolResult(
            ok=True,
            data={
                "path": str(path),
                "tables": tables,
                "table_count": len(tables),
            },
        )

    async def _extract_metadata(self, path: Path) -> ToolResult:
        read_result = await self._read_document(path)
        if not read_result.ok:
            return read_result

        doc_result = read_result.data.get("result", {})

        return ToolResult(
            ok=True,
            data={
                "path": str(path),
                "metadata": doc_result.get("metadata", {}),
                "title": doc_result.get("title"),
                "page_count": doc_result.get("page_count"),
            },
        )

    def _build_result(self, path: Path, parse_result: ParseResult) -> ToolResult:
        logger.debug("_build_result: path=%s, ok=%s, text_len=%d, tables=%d, images=%d",
                     path, parse_result.ok, len(parse_result.text), len(parse_result.tables), len(parse_result.images))

        formatted_tables = []
        for i, tab in enumerate(parse_result.tables):
            if isinstance(tab, list):
                formatted_tables.append({"index": i, "rows": tab})
            elif isinstance(tab, dict):
                formatted_tables.append({"index": i, **tab})
            else:
                formatted_tables.append({"index": i, "text": str(tab)})

        doc_result = DocumentResult(
            title=parse_result.title,
            page_count=parse_result.page_count,
            sections=parse_result.sections,
            tables=formatted_tables,
            images=parse_result.images,
            text=parse_result.text,
            metadata=parse_result.metadata,
        )

        return ToolResult(
            ok=True,
            data={
                "path": str(path),
                "result": doc_result.to_dict(),
            },
        )