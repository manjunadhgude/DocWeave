"""Tests for the opt-in OCR integration."""

import pytest
from pypdf import PdfWriter

from docweave.pdf_fields import extract_pdf_fields
from docweave.pdf_ingest import PDFLoadError, extract_pdf_text
import docweave.pdf_ocr as pdf_ocr
from test_pdf_ingest import make_text_pdf


def blank_pdf(path):
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def test_ocr_is_opt_in(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "blank.pdf")

    def must_not_run(*args, **kwargs):
        raise AssertionError("OCR should not run unless explicitly enabled")

    monkeypatch.setattr(pdf_ocr, "extract_ocr_pages", must_not_run)
    with pytest.raises(PDFLoadError) as caught:
        extract_pdf_text(path, "invoice")
    assert caught.value.code == "PDF_NO_EXTRACTABLE_TEXT"


def test_missing_ocr_engine_returns_structured_error(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "scanned.pdf")

    def unavailable(*args, **kwargs):
        raise pdf_ocr.PDFOCREngineUnavailable("OCR unavailable in test")

    monkeypatch.setattr(pdf_ocr, "extract_ocr_pages", unavailable)
    with pytest.raises(PDFLoadError) as caught:
        extract_pdf_text(path, "invoice", enable_ocr=True)
    assert caught.value.code == "PDF_OCR_UNAVAILABLE"


def test_ocr_text_is_marked_and_keeps_page_number(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "scanned.pdf")
    text = "Invoice No: INV-1"

    monkeypatch.setattr(
        pdf_ocr,
        "extract_ocr_pages",
        lambda path, max_pages, page_numbers=None: [{
            "page_number": 1,
            "text": text,
            "character_count": len(text),
        }],
    )
    result, source = extract_pdf_text(path, "invoice", enable_ocr=True)
    assert result["pages"][0]["page_number"] == 1
    assert source["extraction_method"] == "ocr"
    assert any("OCR may introduce recognition errors" in item
               for item in result["limitations"])


def test_field_extraction_still_requires_review_for_incomplete_ocr(
    tmp_path, monkeypatch
):
    path = blank_pdf(tmp_path / "scanned.pdf")
    text = "Invoice No: INV-1"

    monkeypatch.setattr(
        pdf_ocr,
        "extract_ocr_pages",
        lambda path, max_pages, page_numbers=None: [{
            "page_number": 1,
            "text": text,
            "character_count": len(text),
        }],
    )
    report = extract_pdf_fields(path, "invoice", enable_ocr=True)
    assert report["status"] == "NEEDS_REVIEW"
    assert report["document"] is None

def test_hybrid_pdf_ocr_only_processes_pages_without_selectable_text(
    tmp_path, monkeypatch
):
    path = tmp_path / "mixed.pdf"
    make_text_pdf(path, ["Native digital text", ""])
    calls = {}
    recognized_text = "Scanned page recognized by OCR"

    def fake_ocr(path, max_pages, page_numbers=None):
        calls["page_numbers"] = page_numbers
        return [{
            "page_number": 2,
            "text": recognized_text,
            "character_count": len(recognized_text),
        }]

    monkeypatch.setattr(pdf_ocr, "extract_ocr_pages", fake_ocr)
    result, source = extract_pdf_text(path, "invoice", enable_ocr=True)

    assert "Native digital text" in result["pages"][0]["text"]
    assert result["pages"][1]["text"] == recognized_text
    assert calls["page_numbers"] == [2]
    assert source["extraction_method"] == "hybrid"



def _install_fake_ocr_backend(monkeypatch, *, ocr_error=None, image_error=None):
    """Install fake PDFium/Tesseract modules and track resource cleanup."""
    import sys
    from types import ModuleType

    state = {
        "image_closed": False,
        "bitmap_closed": False,
        "page_closed": False,
        "document_closed": False,
    }

    class FakeImage:
        def close(self):
            state["image_closed"] = True

    image = FakeImage()

    class FakeBitmap:
        def to_pil(self):
            if image_error is not None:
                raise image_error
            return image

        def close(self):
            state["bitmap_closed"] = True

    bitmap = FakeBitmap()

    class FakePage:
        def render(self, scale):
            return bitmap

        def close(self):
            state["page_closed"] = True

    page = FakePage()

    class FakeDocument:
        def __len__(self):
            return 1

        def __getitem__(self, index):
            assert index == 0
            return page

        def close(self):
            state["document_closed"] = True

    document = FakeDocument()
    fake_pdfium = ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = lambda path: document

    fake_tesseract = ModuleType("pytesseract")

    def image_to_string(image_arg):
        if ocr_error is not None:
            raise ocr_error
        return "recognized text"

    fake_tesseract.image_to_string = image_to_string

    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)
    monkeypatch.setattr(
        pdf_ocr.shutil, "which", lambda executable: "/usr/bin/tesseract"
    )
    return state


def test_ocr_closes_resources_after_success(monkeypatch):
    state = _install_fake_ocr_backend(monkeypatch)

    pages = pdf_ocr.extract_ocr_pages("fake.pdf", page_numbers=[1])

    assert pages[0]["text"] == "recognized text"
    assert state["image_closed"]
    assert state["bitmap_closed"]
    assert state["page_closed"]
    assert state["document_closed"]


def test_ocr_closes_resources_when_recognition_fails(monkeypatch):
    state = _install_fake_ocr_backend(
        monkeypatch, ocr_error=RuntimeError("simulated OCR failure")
    )

    with pytest.raises(RuntimeError, match="simulated OCR failure"):
        pdf_ocr.extract_ocr_pages("fake.pdf", page_numbers=[1])

    assert state["image_closed"]
    assert state["bitmap_closed"]
    assert state["page_closed"]
    assert state["document_closed"]


def test_ocr_closes_resources_when_image_conversion_fails(monkeypatch):
    state = _install_fake_ocr_backend(
        monkeypatch,
        image_error=RuntimeError("simulated image conversion failure"),
    )

    with pytest.raises(RuntimeError, match="simulated image conversion failure"):
        pdf_ocr.extract_ocr_pages("fake.pdf", page_numbers=[1])

    assert state["bitmap_closed"]
    assert state["page_closed"]
    assert state["document_closed"]


def test_empty_ocr_output_returns_no_extractable_text_error(tmp_path, monkeypatch):
    path = blank_pdf(tmp_path / "empty-ocr.pdf")

    monkeypatch.setattr(
        pdf_ocr,
        "extract_ocr_pages",
        lambda path, max_pages, page_numbers=None: [{
            "page_number": 1,
            "text": "",
            "character_count": 0,
        }],
    )

    with pytest.raises(PDFLoadError) as caught:
        extract_pdf_text(path, "invoice", enable_ocr=True)

    assert caught.value.code == "PDF_NO_EXTRACTABLE_TEXT"


# Page-selection safety tests. These use fake PDFium/Tesseract modules, so
# they do not require OCR packages or a system Tesseract installation.
def _install_multi_page_ocr_backend(monkeypatch, page_count=3):
    import sys
    from types import ModuleType

    state = {"opened_pages": [], "closed_pages": [], "rendered_pages": [],
             "document_closed": False}

    class FakeImage:
        def close(self):
            pass

    class FakeBitmap:
        def to_pil(self):
            return FakeImage()

        def close(self):
            pass

    class FakePage:
        def __init__(self, page_number):
            self.page_number = page_number

        def render(self, scale):
            state["rendered_pages"].append(self.page_number)
            return FakeBitmap()

        def close(self):
            state["closed_pages"].append(self.page_number)

    pages = [FakePage(number) for number in range(1, page_count + 1)]

    class FakeDocument:
        def __len__(self):
            return len(pages)

        def __getitem__(self, index):
            state["opened_pages"].append(index + 1)
            return pages[index]

        def close(self):
            state["document_closed"] = True

    fake_pdfium = ModuleType("pypdfium2")
    fake_pdfium.PdfDocument = lambda path: FakeDocument()
    fake_tesseract = ModuleType("pytesseract")
    fake_tesseract.image_to_string = lambda image: "recognized text"

    monkeypatch.setitem(sys.modules, "pypdfium2", fake_pdfium)
    monkeypatch.setitem(sys.modules, "pytesseract", fake_tesseract)
    monkeypatch.setattr(
        pdf_ocr.shutil, "which", lambda executable: "/usr/bin/tesseract"
    )
    return state


def test_ocr_rejects_pdf_over_page_limit_before_rendering(monkeypatch):
    state = _install_multi_page_ocr_backend(monkeypatch, page_count=3)

    with pytest.raises(pdf_ocr.PDFOCREngineUnavailable, match="page limit"):
        pdf_ocr.extract_ocr_pages("fake.pdf", max_pages=2)

    assert state["opened_pages"] == []
    assert state["rendered_pages"] == []
    assert state["document_closed"] is True


def test_ocr_rejects_non_numeric_page_selection_and_closes_document(monkeypatch):
    state = _install_multi_page_ocr_backend(monkeypatch)

    with pytest.raises(
        pdf_ocr.PDFOCREngineUnavailable, match="valid page numbers"
    ):
        pdf_ocr.extract_ocr_pages("fake.pdf", page_numbers=[1, "not-a-page"])

    assert state["opened_pages"] == []
    assert state["document_closed"] is True


def test_ocr_rejects_out_of_range_page_selection_and_closes_document(monkeypatch):
    state = _install_multi_page_ocr_backend(monkeypatch, page_count=3)

    with pytest.raises(
        pdf_ocr.PDFOCREngineUnavailable, match="outside the PDF"
    ):
        pdf_ocr.extract_ocr_pages("fake.pdf", page_numbers=[1, 4])

    assert state["opened_pages"] == []
    assert state["document_closed"] is True


def test_ocr_sorts_and_deduplicates_selected_pages(monkeypatch):
    state = _install_multi_page_ocr_backend(monkeypatch, page_count=3)

    result = pdf_ocr.extract_ocr_pages(
        "fake.pdf", page_numbers=[3, 1, 3, 2, 1]
    )

    assert [item["page_number"] for item in result] == [1, 2, 3]
    assert state["opened_pages"] == [1, 2, 3]
    assert state["closed_pages"] == [1, 2, 3]
    assert state["document_closed"] is True
