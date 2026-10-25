"""Command-line interface for conservative PDF business-field extraction."""

import argparse
import json
import sys

from docweave.pdf_ingest import PDFLoadError
from docweave.pdf_fields import extract_pdf_fields


ROLES = ("purchase_order", "invoice", "goods_receipt_note")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract labelled business fields and page evidence from a digital PDF."
    )
    parser.add_argument("pdf_path", help="Path to the input PDF")
    parser.add_argument("--role", choices=ROLES, required=True)
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable optional OCR for PDFs with no selectable text",
    )
    args = parser.parse_args(argv)

    try:
        report = extract_pdf_fields(
            args.pdf_path, args.role, enable_ocr=args.ocr
        )
    except PDFLoadError as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "error": error.to_dict(),
        }, indent=2, ensure_ascii=False))
        return 2
    except ValueError as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "error": {"code": "INVALID_REQUEST", "message": str(error)},
        }, indent=2, ensure_ascii=False))
        return 2

    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "EXTRACTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
