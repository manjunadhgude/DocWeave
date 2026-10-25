"""Command-line interface for page-aware PDF text extraction."""

import argparse
import json
import sys

from docweave.pdf_ingest import PDFLoadError, extract_pdf_text


ROLES = ("purchase_order", "invoice", "goods_receipt_note")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract text and page-level evidence from a digital PDF."
    )
    parser.add_argument("pdf_path", help="Path to the input PDF")
    parser.add_argument(
        "--role",
        choices=ROLES,
        required=True,
        help="Business-document role for source tracking",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable optional OCR for PDFs with no selectable text",
    )
    args = parser.parse_args(argv)

    try:
        result, source = extract_pdf_text(
            args.pdf_path, args.role, enable_ocr=args.ocr
        )
    except PDFLoadError as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "error": error.to_dict(),
        }, indent=2, ensure_ascii=False))
        return 2

    output = {"status": result["status"], "source": source, **result}
    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
