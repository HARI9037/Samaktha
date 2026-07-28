import hashlib
import json
import logging
import os
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path

from app.fileparsers.base import DocumentParser, ParseResult

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(tempfile.gettempdir()) / "samaktha_ocr_cache"
_WORKER_PATH = Path(__file__).resolve().parent / "ocr_worker.py"
_EASYOCR_AVAILABLE: bool | None = None


class OCRParser(DocumentParser):
    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp")

    def parse(self, path: Path) -> ParseResult:
        logger.info("OCRParser: START path=%s", path)
        cached = self._load_cache(path)
        if cached is not None:
            logger.info("OCRParser: CACHE HIT for %s (text_len=%d)", path, len(cached.text))
            return cached

        if self._is_easyocr_available():
            result = self._parse_via_easyocr(path)
            if result.ok:
                self._save_cache(path, result)
                logger.info("OCRParser: SUCCESS via EasyOCR — text_len=%d", len(result.text))
                return result
            logger.warning("OCRParser: EasyOCR failed for %s (error=%s), trying Tesseract fallback", path, result.error)

        if self._is_tesseract_available():
            result = self._parse_via_tesseract(path)
            if result.ok:
                self._save_cache(path, result)
                logger.info("OCRParser: SUCCESS via Tesseract — text_len=%d", len(result.text))
                return result
            logger.warning("OCRParser: Tesseract failed for %s (error=%s)", path, result.error)

        file_size = 0
        try:
            file_size = path.stat().st_size
        except OSError:
            pass

        logger.warning("OCRParser: ALL OCR ENGINES EXHAUSTED for %s", path)
        return ParseResult(
            ok=False,
            error="The document appears to contain no readable text even after OCR.",
            metadata={
                "source_path": str(path),
                "file_size": file_size,
                "format": path.suffix.lower(),
                "scanned_pdf": True,
                "ocr_used": None,
            },
        )

    def _is_easyocr_available(self) -> bool:
        global _EASYOCR_AVAILABLE
        if _EASYOCR_AVAILABLE is not None:
            return _EASYOCR_AVAILABLE
        try:
            result = subprocess.run(
                [sys.executable, "-c", "import easyocr; print('ok')"],
                capture_output=True, timeout=30,
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "USE_CUDA": "0"},
            )
            _EASYOCR_AVAILABLE = result.returncode == 0 and b"ok" in result.stdout
        except Exception:
            _EASYOCR_AVAILABLE = False
        return _EASYOCR_AVAILABLE

    def _parse_via_easyocr(self, path: Path) -> ParseResult:
        try:
            result = subprocess.run(
                [sys.executable, str(_WORKER_PATH), str(path)],
                capture_output=True, timeout=300,
                env={**os.environ, "CUDA_VISIBLE_DEVICES": "-1", "USE_CUDA": "0"},
            )
        except subprocess.TimeoutExpired:
            return ParseResult(
                ok=False, error="EasyOCR subprocess timed out (300s).",
                metadata={"scanned_pdf": True, "ocr_used": "easyocr_failed"},
            )
        except Exception as e:
            return ParseResult(
                ok=False, error=f"EasyOCR subprocess launch failed: {e}",
                metadata={"scanned_pdf": True, "ocr_used": "easyocr_failed"},
            )

        if result.returncode != 0:
            err = (result.stderr.decode().strip() or
                   f"Worker exited with code {result.returncode}")
            return ParseResult(
                ok=False, error=err,
                metadata={"scanned_pdf": True, "ocr_used": "easyocr_failed"},
            )

        try:
            data = json.loads(result.stdout.decode().strip())
        except (json.JSONDecodeError, ValueError):
            return ParseResult(
                ok=False, error="EasyOCR worker returned invalid JSON.",
                metadata={"scanned_pdf": True, "ocr_used": "easyocr_failed"},
            )

        if data.get("success"):
            return ParseResult(
                ok=True,
                text=data["text"],
                title=path.stem,
                page_count=data.get("page_count", 1),
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "ocr",
                    "ocr_used": "easyocr",
                    "scanned_pdf": True,
                },
            )

        return ParseResult(
            ok=False,
            error=data.get("error", "EasyOCR processing failed."),
            metadata={"scanned_pdf": True, "ocr_used": "easyocr_failed"},
        )

    def _is_tesseract_available(self) -> bool:
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            return True
        except Exception:
            return False

    def _parse_via_tesseract(self, path: Path) -> ParseResult:
        try:
            import pytesseract
            from PIL import Image
        except ImportError:
            return ParseResult(
                ok=False, error="pytesseract not installed.",
                metadata={"scanned_pdf": True, "ocr_used": "tesseract_unavailable"},
            )

        try:
            import fitz
        except ImportError:
            return ParseResult(
                ok=False, error="PyMuPDF not available for image extraction.",
                metadata={"scanned_pdf": True, "ocr_used": "tesseract_unavailable"},
            )

        try:
            logger.debug("OCRParser: starting PyMuPDF+Tesseract OCR for %s", path)

            if path.suffix.lower() == ".pdf":
                pdf_doc = fitz.open(str(path))
                page_count = pdf_doc.page_count
                text_parts = []

                for idx in range(page_count):
                    page = pdf_doc[idx]
                    pix = page.get_pixmap(dpi=300)
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    page_text = pytesseract.image_to_string(img)
                    if page_text:
                        text_parts.append(page_text.strip())

                pdf_doc.close()
            else:
                page_count = 1
                img = Image.open(str(path))
                page_text = pytesseract.image_to_string(img)
                text_parts = [page_text.strip()] if page_text else []

            text = "\n".join(text_parts)

            logger.debug("OCRParser: Tesseract OCR text_len=%d, pages=%d", len(text), page_count)

            if text.strip():
                return ParseResult(
                    ok=True,
                    text=text,
                    title=path.stem,
                    page_count=page_count,
                    metadata={
                        "source_path": str(path),
                        "file_size": path.stat().st_size,
                        "format": path.suffix.lower(),
                        "parser": "ocr",
                        "ocr_used": "tesseract",
                        "scanned_pdf": True,
                    },
                )

            logger.info("OCRParser: Tesseract found no text in %s", path)
            return ParseResult(
                ok=False,
                text="",
                title=path.stem,
                page_count=page_count,
                error="Tesseract found no text in the document.",
                metadata={
                    "source_path": str(path),
                    "file_size": path.stat().st_size,
                    "format": path.suffix.lower(),
                    "parser": "ocr",
                    "ocr_used": "tesseract",
                    "scanned_pdf": True,
                },
            )

        except Exception as e:
            logger.warning("OCRParser: Tesseract OCR exception: %s\n%s", e, traceback.format_exc())
            return ParseResult(
                ok=False, error="Tesseract OCR failed.",
                metadata={"scanned_pdf": True, "ocr_used": "tesseract_failed"},
            )

    # ── Caching ─────────────────────────────────────────────────────

    def _cache_key(self, path: Path) -> str:
        try:
            stat = path.stat()
            raw = f"{path.resolve()}|{stat.st_mtime_ns}|{stat.st_size}"
        except OSError:
            raw = str(path.resolve())
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return h

    def _cache_path(self, key: str) -> Path:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return _CACHE_DIR / f"{key}.json"

    def _load_cache(self, path: Path) -> ParseResult | None:
        key = self._cache_key(path)
        cache_file = self._cache_path(key)
        if not cache_file.exists():
            return None
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ParseResult(
                ok=data["ok"],
                text=data.get("text", ""),
                title=data.get("title"),
                page_count=data.get("page_count", 0),
                sections=data.get("sections", []),
                tables=data.get("tables", []),
                images=data.get("images", []),
                metadata=data.get("metadata", {}),
            )
        except Exception as e:
            logger.debug("OCRParser: cache read error for %s: %s", path, e)
            return None

    def _save_cache(self, path: Path, result: ParseResult) -> None:
        key = self._cache_key(path)
        cache_file = self._cache_path(key)
        try:
            _CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump({
                    "ok": result.ok,
                    "text": result.text,
                    "title": result.title,
                    "page_count": result.page_count,
                    "sections": result.sections,
                    "tables": result.tables,
                    "images": result.images,
                    "metadata": result.metadata,
                }, f, ensure_ascii=False)
        except Exception as e:
            logger.debug("OCRParser: cache write error for %s: %s", path, e)
