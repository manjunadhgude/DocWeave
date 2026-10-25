"""CLI for end-to-end reconciliation of three digital PDF documents."""

import argparse
import json

from docweave.pdf_three_way import reconcile_pdf_documents


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Extract and reconcile a purchase order, invoice and GRN PDF."
    )
    parser.add_argument("purchase_order_pdf")
    parser.add_argument("invoice_pdf")
    parser.add_argument("goods_receipt_note_pdf")
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable optional OCR for scanned PDFs",
    )
    args = parser.parse_args(argv)

    report = reconcile_pdf_documents(
        args.purchase_order_pdf,
        args.invoice_pdf,
        args.goods_receipt_note_pdf,
        enable_ocr=args.ocr,
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if report["status"] == "MATCH":
        return 0
    if report["status"] == "NEEDS_REVIEW":
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
