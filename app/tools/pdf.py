import os
import re
import zlib
from pathlib import Path
from typing import Any, Dict

from app.tools.base import Tool, ToolResult
from app.tools.resolver import FileResolver, MultipleMatches


class PDFTool(Tool):
    """Tool for reading and analyzing PDF documents (extract text, page count, metadata)."""

    def __init__(self, root_dir: str | Path | None = None) -> None:
        self._resolver = FileResolver(root_dir)

    @property
    def name(self) -> str:
        return "pdf"

    async def run(self, arguments: Dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "extract_text")
        path_str = arguments.get("path") or arguments.get("target_path")

        if not path_str:
            return ToolResult(ok=False, error="Missing required argument 'path'")

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
        
        if not target_path.exists():
            return ToolResult(ok=False, error=f"PDF file does not exist: {target_path}")

        try:
            if action in ("extract_text", "read", "read_pdf"):
                text, page_count = self._extract_text(target_path)
                return ToolResult(
                    ok=True,
                    data={
                        "path": str(target_path),
                        "text": text,
                        "page_count": page_count,
                        "character_count": len(text),
                    },
                )
            elif action == "page_count":
                _, page_count = self._extract_text(target_path)
                return ToolResult(ok=True, data={"path": str(target_path), "page_count": page_count})
            elif action == "metadata":
                _, page_count = self._extract_text(target_path)
                return ToolResult(
                    ok=True,
                    data={
                        "path": str(target_path),
                        "page_count": page_count,
                        "file_size_bytes": target_path.stat().st_size,
                    },
                )
            elif action == "tables":
                return ToolResult(
                    ok=True,
                    data={
                        "path": str(target_path),
                        "tables": [],
                        "note": "Table extraction placeholder active.",
                    },
                )
            else:
                return ToolResult(ok=False, error=f"Unsupported PDF action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=f"PDF processing failed: {str(e)}")

    def _extract_text(self, pdf_path: Path) -> tuple[str, int]:
        # 1. Try pypdf if installed
        try:
            import pypdf
            reader = pypdf.PdfReader(str(pdf_path))
            pages_text = []
            for idx, page in enumerate(reader.pages):
                txt = page.extract_text() or ""
                pages_text.append(f"--- Page {idx + 1} ---\n{txt.strip()}")
            return "\n\n".join(pages_text), len(reader.pages)
        except Exception:
            pass

        # 2. Native PDF byte stream parser fallback
        raw_bytes = pdf_path.read_bytes()
        
        # Estimate page count from /Type /Page
        page_matches = re.findall(rb"/Type\s*/Page\b", raw_bytes)
        page_count = max(1, len(page_matches))

        # Find stream objects
        streams = re.findall(rb"stream\r?\n(.*?)\r?\nendstream", raw_bytes, re.DOTALL)
        extracted_chunks = []

        for stream in streams:
            try:
                decompressed = zlib.decompress(stream)
            except Exception:
                decompressed = stream

            # Extract text from PDF Tj / TJ text operators
            # Tj pattern: (text) Tj
            tj_matches = re.findall(rb"\((.*?)\)\s*Tj", decompressed)
            for m in tj_matches:
                try:
                    txt = m.decode("latin-1", errors="ignore")
                    if txt.strip():
                        extracted_chunks.append(txt)
                except Exception:
                    pass

            # TJ array pattern: [(chunk) 10 (chunk2)] TJ
            tj_array_matches = re.findall(rb"\[(.*?)\]\s*TJ", decompressed)
            for array_content in tj_array_matches:
                chunks = re.findall(rb"\((.*?)\)", array_content)
                str_parts = []
                for c in chunks:
                    try:
                        str_parts.append(c.decode("latin-1", errors="ignore"))
                    except Exception:
                        pass
                combined = "".join(str_parts).strip()
                if combined:
                    extracted_chunks.append(combined)

        full_text = " ".join(extracted_chunks).strip()
        if not full_text:
            # Fallback string regex extraction if text stream structure was non-standard
            text_tokens = re.findall(r"[\x20-\x7E]{4,}", raw_bytes.decode("latin-1", errors="ignore"))
            filtered = [t for t in text_tokens if not t.startswith(("/", "obj", "endobj", "stream", "endstream", "xref"))]
            full_text = "\n".join(filtered[:50])

        return full_text, page_count
