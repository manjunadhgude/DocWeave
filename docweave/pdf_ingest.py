"""Safe, page-aware text extraction from digital PDF documents."""

import hashlib
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_PAGES = 200


class PDFLoadError(ValueError):
    """Structured error raised when a PDF cannot be safely extracted."""

    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self):
        return {"code": self.code, "message": self.message, **self.details}


def extract_pdf_text(
    path,
    role,
    max_bytes=DEFAULT_MAX_BYTES,
    max_pages=DEFAULT_MAX_PAGES,
):
    """Extract text page by page and return (result, source_metadata).

    This function extracts text only. It does not infer invoice fields or
    assert that extracted text is accurate, complete, or authentic.
    """
    path = Path(path)
    context = {"document_role": role, "file_name": path.name}

    try:
        size = path.stat().st_size
    except OSError as error:
        raise PDFLoadError(
            "FILE_READ_ERROR",
            f"Could not access {path.name}: "
            f"{error.strerror or 'file access failed'}",
            context,
        ) from None

    if size > max_bytes:
        raise PDFLoadError(
            "PDF_TOO_LARGE",
            f"PDF exceeds the configured {max_bytes}-byte size limit.",
            {**context, "byte_size": size, "max_bytes": max_bytes},
        )

    try:
        raw = path.read_bytes()
    except OSError as error:
        raise PDFLoadError(
            "FILE_READ_ERROR",
            f"Could not read {path.name}: "
            f"{error.strerror or 'file access failed'}",
            context,
        ) from None

    if not raw.startswith(b"%PDF-"):
        raise PDFLoadError(
            "INVALID_PDF",
            "The file does not start with a PDF header.",
            context,
        )

    try:
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise PDFLoadError(
                "PDF_ENCRYPTED",
                "This PDF is encrypted; provide an authorized, readable copy.",
                context,
            )

        page_count = len(reader.pages)
        if page_count == 0:
            raise PDFLoadError(
                "PDF_NO_PAGES", "The PDF contains no pages.", context
            )
        if page_count > max_pages:
            raise PDFLoadError(
                "PDF_TOO_MANY_PAGES",
                f"PDF exceeds the configured {max_pages}-page limit.",
                {**context, "page_count": page_count, "max_pages": max_pages},
            )

        pages = []
        for index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception as error:
                raise PDFLoadError(
                    "PDF_PAGE_EXTRACTION_FAILED",
                    f"Text extraction failed on page {index}: "
                    f"{type(error).__name__}.",
                    {**context, "page_number": index},
                ) from None

            pages.append({
                "page_number": index,
                "text": text,
                "character_count": len(text),
            })

    except PDFLoadError:
        raise
    except (PdfReadError, OSError, ValueError, TypeError, KeyError) as error:
        raise PDFLoadError(
            "INVALID_PDF",
            f"The PDF could not be parsed ({type(error).__name__}).",
            context,
        ) from None
    except Exception as error:
        raise PDFLoadError(
            "PDF_EXTRACTION_FAILED",
            f"PDF processing failed ({type(error).__name__}).",
            context,
        ) from None

    total_characters = sum(page["character_count"] for page in pages)
    if not any(page["text"].strip() for page in pages):
        raise PDFLoadError(
            "PDF_NO_EXTRACTABLE_TEXT",
            "No selectable text was found. The PDF may contain scanned "
            "images and may need OCR.",
            {
                **context,
                "page_count": page_count,
                "character_count": total_characters,
            },
        )

    source = {
        **context,
        "format": "pdf",
        "byte_size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }

    result = {
        "status": "TEXT_EXTRACTED",
        "page_count": page_count,
        "character_count": total_characters,
        "pages": pages,
        "limitations": [
            "Text extraction does not identify or validate business fields.",
            "Text order and completeness depend on the PDF's internal structure.",
            "Scanned pages without a text layer require OCR.",
            "Extracted text does not prove document authenticity.",
        ],
    }
    return result, source
