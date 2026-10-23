import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfWriter

from docweave.pdf_ingest import PDFLoadError, extract_pdf_text
from docweave.pdf_cli import main


def make_text_pdf(path, texts):
    """Create a tiny standards-compliant PDF fixture with selectable text."""
    objects = []

    def add_object(value):
        objects.append(value.encode("latin-1"))
        return len(objects)

    catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
    pages_id = add_object("")

    page_ids = []
    content_ids = []

    for _ in texts:
        page_ids.append(add_object(""))
        content_ids.append(add_object(""))

    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = (
        f"<< /Type /Pages /Kids [{kids}] /Count {len(texts)} >>".encode()
    )

    for index, value in enumerate(texts):
        safe = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({safe}) Tj ET".encode("latin-1")
        content_id = content_ids[index]
        objects[content_id - 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode()
            + stream + b"\nendstream"
        )
        page_id = page_ids[index]
        objects[page_id - 1] = (
            f"<< /Type /Page /Parent {pages_id} 0 R "
            f"/MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode()

    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode())
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode())

    output.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode()
    )
    path.write_bytes(output)


class PDFIngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_extracts_text_by_page_and_fingerprints_source(self):
        path = self.root / "invoice.pdf"
        make_text_pdf(path, ["Invoice INV-1", "Total INR 500"])

        result, source = extract_pdf_text(path, "invoice")

        self.assertEqual(result["status"], "TEXT_EXTRACTED")
        self.assertEqual(result["page_count"], 2)
        self.assertIn("Invoice INV-1", result["pages"][0]["text"])
        self.assertIn("Total INR 500", result["pages"][1]["text"])
        self.assertEqual(
            [p["page_number"] for p in result["pages"]], [1, 2]
        )
        self.assertEqual(
            source["sha256"], hashlib.sha256(path.read_bytes()).hexdigest()
        )
        self.assertEqual(source["byte_size"], path.stat().st_size)
        self.assertEqual(source["document_role"], "invoice")

    def test_invalid_header_is_rejected(self):
        path = self.root / "fake.pdf"
        path.write_bytes(b"not a PDF")
        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(path, "invoice")
        self.assertEqual(caught.exception.code, "INVALID_PDF")

    def test_missing_file_has_structured_error(self):
        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(self.root / "missing.pdf", "invoice")
        self.assertEqual(caught.exception.code, "FILE_READ_ERROR")

    def test_oversized_file_is_rejected_before_parsing(self):
        path = self.root / "large.pdf"
        path.write_bytes(b"%PDF-" + b"x" * 50)
        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(path, "invoice", max_bytes=20)
        self.assertEqual(caught.exception.code, "PDF_TOO_LARGE")

    def test_blank_pdf_returns_no_extractable_text(self):
        path = self.root / "blank.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        with path.open("wb") as stream:
            writer.write(stream)

        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(path, "invoice")
        self.assertEqual(
            caught.exception.code, "PDF_NO_EXTRACTABLE_TEXT"
        )

    def test_page_limit_is_enforced(self):
        path = self.root / "two-pages.pdf"
        make_text_pdf(path, ["First page", "Second page"])

        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(path, "invoice", max_pages=1)
        self.assertEqual(caught.exception.code, "PDF_TOO_MANY_PAGES")

    def test_encrypted_pdf_is_rejected(self):
        path = self.root / "encrypted.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=612, height=792)
        writer.encrypt("test-password")
        with path.open("wb") as stream:
            writer.write(stream)

        with self.assertRaises(PDFLoadError) as caught:
            extract_pdf_text(path, "invoice")
        self.assertEqual(caught.exception.code, "PDF_ENCRYPTED")

    def test_cli_returns_page_aware_json(self):
        path = self.root / "po.pdf"
        make_text_pdf(path, ["Purchase Order PO-1"])

        import contextlib
        import io

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(path), "--role", "purchase_order"])

        report = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "TEXT_EXTRACTED")
        self.assertEqual(report["source"]["document_role"], "purchase_order")
        self.assertEqual(report["pages"][0]["page_number"], 1)

    def test_cli_returns_structured_error_for_bad_pdf(self):
        path = self.root / "bad.pdf"
        path.write_bytes(b"not a PDF")

        import contextlib
        import io

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(path), "--role", "invoice"])

        report = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertEqual(report["error"]["code"], "INVALID_PDF")


if __name__ == "__main__":
    unittest.main()
