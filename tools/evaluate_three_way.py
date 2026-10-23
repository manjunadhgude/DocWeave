"""Synthetic smoke evaluation for DocWeave three-way matching."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docweave.three_way import reconcile_three_way


def make_docs(received=5, receipt_supplier="SUP-1"):
    po = {
        "document_id": "PO-EVAL", "supplier_id": "SUP-1", "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    inv = {
        "document_id": "INV-EVAL", "supplier_id": "SUP-1", "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    grn = {
        "document_id": "GRN-EVAL", "supplier_id": receipt_supplier,
        "lines": [{"item_id": "A", "quantity": received}],
    }
    return po, inv, grn


cases = [
    ("exact_match", make_docs(), "MATCH", None),
    ("invoice_exceeds_receipt", make_docs(received=3), "DISCREPANCY",
     "INVOICE_EXCEEDS_RECEIVED_QUANTITY"),
    ("receipt_exceeds_order", make_docs(received=6), "DISCREPANCY",
     "RECEIPT_EXCEEDS_ORDERED_QUANTITY"),
    ("supplier_mismatch", make_docs(receipt_supplier="OTHER"), "DISCREPANCY",
     "RECEIPT_SUPPLIER_MISMATCH"),
]

results = []
for name, docs, expected_status, expected_code in cases:
    report = reconcile_three_way(*docs)
    codes = {f["code"] for f in report["findings"]}
    passed = report["status"] == expected_status
    if expected_code:
        passed = passed and expected_code in codes
    results.append({
        "scenario": name, "passed": passed,
        "expected_status": expected_status, "actual_status": report["status"],
        "expected_finding": expected_code,
    })

passed = sum(x["passed"] for x in results)
print(json.dumps({
    "evaluation": "DocWeave three-way synthetic evaluation",
    "passed": passed, "total": len(results),
    "pass_rate": round(passed / len(results), 4), "results": results,
}, indent=2))
raise SystemExit(0 if passed == len(results) else 1)
