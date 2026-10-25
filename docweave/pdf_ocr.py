"""Optional OCR adapter for scanned PDFs."""

import shutil
from pathlib import Path


class PDFOCREngineUnavailable(RuntimeError):
    """Optional OCR dependencies or the Tesseract executable are unavailable."""


def extract_ocr_pages(path, max_pages=200, page_numbers=None):
    """Render PDF pages and recognize text using Tesseract."""
    try:
        import pypdfium2 as pdfium
        import pytesseract
    except ImportError:
        raise PDFOCREngineUnavailable(
            "OCR needs the optional pypdfium2 and pytesseract Python packages "
            "and the Tesseract OCR engine."
        ) from None

    if shutil.which("tesseract") is None:
        raise PDFOCREngineUnavailable(
            "The Tesseract executable was not found on PATH."
        )

    document = pdfium.PdfDocument(str(Path(path)))
    try:
        if len(document) > max_pages:
            raise PDFOCREngineUnavailable(
                f"OCR stopped: PDF exceeds the {max_pages}-page limit."
            )

        if page_numbers is None:
            selected_page_numbers = list(range(1, len(document) + 1))
        else:
            try:
                selected_page_numbers = sorted({int(number) for number in page_numbers})
            except (TypeError, ValueError):
                raise PDFOCREngineUnavailable(
                    "OCR page selection must contain valid page numbers."
                ) from None
            if any(number < 1 or number > len(document) for number in selected_page_numbers):
                raise PDFOCREngineUnavailable(
                    "OCR page selection includes a page outside the PDF."
                )

        pages = []
        for page_number in selected_page_numbers:
            page = document[page_number - 1]
            try:
                bitmap = page.render(scale=2.0)
                try:
                    image = bitmap.to_pil()
                    try:
                        text = pytesseract.image_to_string(image) or ""
                    finally:
                        image.close()
                finally:
                    bitmap.close()
                pages.append(
                    {
                        "page_number": page_number,
                        "text": text,
                        "character_count": len(text),
                    }
                )
            finally:
                page.close()
        return pages
    finally:
        document.close()
