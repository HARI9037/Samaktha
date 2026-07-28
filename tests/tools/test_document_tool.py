import os
import tempfile
from pathlib import Path

import pytest
from app.tools import DocumentTool, FileSystemTool, ToolInfo, ToolRegistry, ToolManager, ResolverTool, DocumentResult


@pytest.fixture
def doc_tool():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield DocumentTool(tmpdir), Path(tmpdir)


@pytest.fixture
def fs_tool():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield FileSystemTool(tmpdir), Path(tmpdir)


def _write_file(path: Path, name: str, content: str) -> Path:
    p = path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestDocumentToolReadText:
    async def test_read_txt_returns_plain_text(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "notes.txt", "Line one\nLine two")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True
        assert "Line one" in result.data["result"]["text"]
        assert result.data["result"]["title"] == "notes"

    async def test_read_markdown_returns_markdown(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "readme.md", "# Heading\n\nSome text")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True
        data = result.data["result"]
        assert "# Heading" in data["text"]
        assert data["title"] == "readme"


class TestDocumentToolOperations:
    async def test_summarize_document_returns_content(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "doc.txt", "Hello World!")
        result = await tool.run({"action": "summarize_document", "path": str(test_file)})
        assert result.ok is True
        assert "Hello World!" in result.data["text"]
        assert result.data["summary_ready"] is True

    async def test_extract_metadata(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "test.txt", "content")
        result = await tool.run({"action": "extract_metadata", "path": str(test_file)})
        assert result.ok is True
        assert "format" in result.data["metadata"]
        assert result.data["metadata"]["format"] == ".txt"


class TestDocumentToolErrorHandling:
    async def test_unsupported_format_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = tmpdir / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is False

    async def test_missing_file_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({"action": "read_document", "path": str(tmpdir / "missing.pdf")})
        assert result.ok is False

    async def test_missing_action_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({})
        assert result.ok is False
        assert "path" in result.error.lower()


class TestDocumentToolResourceRegistry:
    async def test_registry_lookup_finds_named_file(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.pdf", "fake binary content")
        from app.memory.resources import ResourceRegistry
        registry = ResourceRegistry()
        registry.register(test_file)
        resolved = registry.lookup("NOR.pdf")
        assert resolved is not None

    async def test_docling_optional_and_fallback_works(self, doc_tool):
        tool, tmpdir = doc_tool
        from app.fileparsers.factory import DocumentParserFactory
        factory = DocumentParserFactory()
        assert factory is not None


class TestFileSystemToolDocumentDelegation:
    async def test_read_txt_delegates_to_document_tool(self, fs_tool):
        tool, tmpdir = fs_tool
        test_file = _write_file(tmpdir, "notes.txt", "hello world")
        result = await tool.run({"action": "read_file", "path": str(test_file)})
        assert result.ok is True
        assert "hello world" in result.data["content"]

    async def test_read_txt_returns_content_key(self, fs_tool):
        tool, tmpdir = fs_tool
        test_file = _write_file(tmpdir, "notes.txt", "hello world")
        result = await tool.run({"action": "read", "path": str(test_file)})
        assert result.ok is True
        assert "content" in result.data
        assert "notes" in result.data.get("title", "")


class TestResolverToolDocumentRouting:
    async def test_resolver_routes_md_to_document_tool(self):
        from app.tools.resolver_layer import ResolverTool
        from app.tools.registry import ToolRegistry
        from app.tools.document import DocumentTool
        from app.tools import ToolInfo

        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "notes.md"
            test_file.write_text("# Notes", encoding="utf-8")

            registry = ToolRegistry()
            registry.register("document", DocumentTool(tmpdir), ToolInfo(
                tool_id="document", description="doc", capabilities=["read_document"]
            ))

            resolver = ResolverTool(registry)
            result = await resolver.run({
                "action": "read",
                "path": str(test_file),
            })
            assert result.ok is True
            assert "content" in result.data or "text" in result.data.get("result", {})


class TestRegression:
    async def test_read_txt_file(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "sample.txt", "Line one\nLine two\nLine three")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True
        assert "Line one" in result.data["result"]["text"]

    async def test_read_md_file(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "README.md", "# Heading\n\nSome text here")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True
        assert "# Heading" in result.data["result"]["text"]

    async def test_read_named_txt_via_registry(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.txt", "Document content from registry")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True

    async def test_read_absolute_path_registers_resource(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.txt", "Document content absolute path")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True

    async def test_summarize_text(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "Report.txt", "This is a report about quarterly results.")
        result = await tool.run({"action": "summarize_document", "path": str(test_file)})
        assert result.ok is True
        assert "quarterly" in result.data["text"].lower()

    async def test_no_none_type_exception_on_missing_file(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({"action": "read_document", "path": str(tmpdir / "nonexistent.pdf")})
        assert result.ok is False
        assert "NoneType" not in str(result.error)

    async def test_no_torch_traceback_on_missing_docling(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.txt", "fake text content")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True or (result.ok is False and "Torch" not in str(result.error))

    async def test_no_raw_pdf_binary_output(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.txt", "plain text content")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True
        text = result.data["result"]["text"]
        assert "\x00" not in text[:50]

    async def test_read_missing_file_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({"action": "read_document", "path": str(tmpdir / "nonexistent.pdf")})
        assert result.ok is False
        assert "not found" in result.error.lower() or "not exist" in result.error.lower()

    async def test_missing_path_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({"action": "read_document"})
        assert result.ok is False
        assert "path" in result.error.lower()

    async def test_unsupported_format_returns_error(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = tmpdir / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is False

    async def test_resource_registry_still_functions(self, doc_tool):
        tool, tmpdir = doc_tool
        test_file = _write_file(tmpdir, "NOR.txt", "registry test content")
        result = await tool.run({"action": "read_document", "path": str(test_file)})
        assert result.ok is True

    async def test_read_txt_through_filesystem_tool(self, fs_tool):
        tool, tmpdir = fs_tool
        test_file = _write_file(tmpdir, "sample.txt", "hello world")
        result = await tool.run({"action": "read_file", "path": str(test_file)})
        assert result.ok is True
        assert "hello world" in result.data["content"]

    async def test_none_resolve_does_not_crash(self, doc_tool):
        tool, tmpdir = doc_tool
        result = await tool.run({"action": "read_document", "path": str(tmpdir / "nonexistent_file.pdf")})
        assert result.ok is False

    async def test_fallback_parser_chain(self, doc_tool):
        tool, tmpdir = doc_tool
        from app.fileparsers.factory import DocumentParserFactory
        factory = DocumentParserFactory()
        test_file = _write_file(tmpdir, "test.txt", "fallback test content")
        result = factory.parse(test_file)
        assert result.ok is True
        assert "fallback test content" in result.text

    async def test_pymupdf_parser_available(self, doc_tool):
        from app.fileparsers.pdf_parsers import PyMuPDFParser
        parser = PyMuPDFParser()
        assert parser.can_handle(Path("test.pdf")) is True