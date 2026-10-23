"""Command-line entry point for DocWeave."""

import json
import sys
from pathlib import Path

from docweave.engine import reconcile


def main():
    if len(sys.argv) != 3:
        print("Usage: python -m docweave.cli PURCHASE_ORDER.json INVOICE.json")
        return 2

    try:
        po = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
        invoice = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(json.dumps({
            "status": "NEEDS_REVIEW",
            "reason": str(error),
        }, indent=2))
        return 2

    report = reconcile(po, invoice)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["status"] == "MATCH" else 1


if __name__ == "__main__":
    raise SystemExit(main())
