"""Command-line interface for three-way reconciliation."""

import json
import sys

from docweave.ingest import DocumentLoadError, load_json_document
from docweave.three_way import reconcile_three_way


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        print(
            "Usage: python -m docweave.three_way_cli "
            "PURCHASE_ORDER.json INVOICE.json GOODS_RECEIPT_NOTE.json",
            file=sys.stderr,
        )
        return 2

    try:
        po, po_source = load_json_document(args[0], "purchase_order")
        invoice, invoice_source = load_json_document(args[1], "invoice")
        receipt, receipt_source = load_json_document(
            args[2], "goods_receipt_note"
        )
    except DocumentLoadError as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "error": error.to_dict(),
        }, indent=2, ensure_ascii=False))
        return 2

    report = reconcile_three_way(po, invoice, receipt)
    report["sources"] = {
        "purchase_order": po_source,
        "invoice": invoice_source,
        "goods_receipt_note": receipt_source,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
