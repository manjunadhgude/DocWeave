"""Command-line entry point for DocWeave."""

import json
import sys

from docweave.engine import reconcile
from docweave.ingest import DocumentLoadError, load_json_document


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2:
        print(
            "Usage: python -m docweave.cli PURCHASE_ORDER.json INVOICE.json",
            file=sys.stderr,
        )
        return 2

    try:
        po, po_source = load_json_document(args[0], "purchase_order")
        invoice, invoice_source = load_json_document(args[1], "invoice")
    except DocumentLoadError as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "error": error.to_dict(),
        }, indent=2, ensure_ascii=False))
        return 2

    report = reconcile(po, invoice)
    report["sources"] = {
        "purchase_order": po_source,
        "invoice": invoice_source,
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
