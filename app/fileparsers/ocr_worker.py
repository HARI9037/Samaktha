"""Subprocess worker for EasyOCR execution.

Runs in an isolated process to avoid importing torch/easyocr
in the main process where Windows DLL conflicts can occur.
"""
import json
import os
import sys
import tempfile
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2:
        _fail("No file path provided")
        return

    file_path = Path(sys.argv[1])
    if not file_path.exists():
        _fail(f"File not found: {file_path}")
        return

    os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
    os.environ["USE_CUDA"] = "0"

    suffix = file_path.suffix.lower()
    if suffix == ".pdf":
        _process_pdf(file_path)
    else:
        _process_image(file_path)


def _process_pdf(path: Path) -> None:
    import fitz

    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception as e:
        _fail(f"EasyOCR init failed: {e}")
        return

    try:
        pdf_doc = fitz.open(str(path))
    except Exception as e:
        _fail(f"Failed to open PDF: {e}")
        return

    page_count = pdf_doc.page_count
    text_parts = []

    for idx in range(page_count):
        page = pdf_doc[idx]
        pix = page.get_pixmap(dpi=300)
        img_bytes = pix.tobytes("png")
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                tmp_path = tmp.name
                tmp.write(img_bytes)
            results = reader.readtext(tmp_path, detail=0, paragraph=True)
            if results:
                text_parts.append("\n".join(results))
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    pdf_doc.close()
    text = "\n".join(text_parts)

    if text.strip():
        _ok(text, page_count)
    else:
        _fail("EasyOCR found no text in the document.")


def _process_image(path: Path) -> None:
    try:
        import easyocr
        reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    except Exception as e:
        _fail(f"EasyOCR init failed: {e}")
        return

    try:
        results = reader.readtext(str(path), detail=0, paragraph=True)
        text = "\n".join(results) if results else ""
    except Exception as e:
        _fail(f"EasyOCR image processing failed: {e}")
        return

    if text.strip():
        _ok(text, 1)
    else:
        _fail("EasyOCR found no text in the image.")


def _ok(text: str, page_count: int) -> None:
    print(json.dumps({
        "success": True,
        "text": text,
        "page_count": page_count,
        "error": None,
    }))


def _fail(error: str) -> None:
    print(json.dumps({
        "success": False,
        "text": "",
        "page_count": 0,
        "error": error,
    }))


if __name__ == "__main__":
    main()
