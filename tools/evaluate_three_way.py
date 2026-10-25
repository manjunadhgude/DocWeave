"""Expanded synthetic policy checks for DocWeave three-way reconciliation."""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docweave.engine import reconcile
from docweave.three_way import reconcile_three_way


def documents():
    po = {
        "document_id": "PO-EVAL",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    invoice = {
        "document_id": "INV-EVAL",
        "supplier_id": "SUP-1",
        "currency": "INR",
        "lines": [{"item_id": "A", "quantity": 5, "unit_price": 100}],
        "total": 500,
    }
    grn = {
        "document_id": "GRN-EVAL",
        "supplier_id": "SUP-1",
        "lines": [{"item_id": "A", "quantity": 5}],
    }
    return po, invoice, grn


def check_three_way(name, mutate, expected_status, expected_codes=()):
    po, invoice, grn = documents()
    mutate(po, invoice, grn)
    report = reconcile_three_way(po, invoice, grn)
    codes = sorted(f["code"] for f in report.get("findings", []))
    expected = sorted(expected_codes)
    passed = (
        report.get("status") == expected_status
        and codes == expected
    )
    return {
        "scenario": name,
        "passed": passed,
        "expected_status": expected_status,
        "actual_status": report.get("status"),
        "required_findings": list(expected_codes),
        "actual_findings": sorted(codes),
    }


def noop(po, invoice, grn):
    pass


def invoice_exceeds_receipt(po, invoice, grn):
    grn["lines"][0]["quantity"] = 3


def receipt_exceeds_order(po, invoice, grn):
    grn["lines"][0]["quantity"] = 6


def supplier_mismatch(po, invoice, grn):
    grn["supplier_id"] = "SUP-OTHER"


def unexpected_receipt_item(po, invoice, grn):
    grn["lines"].append({"item_id": "B", "quantity": 1})


def invoice_item_replaced(po, invoice, grn):
    invoice["lines"] = [{"item_id": "B", "quantity": 5, "unit_price": 100}]


def quantity_mismatch(po, invoice, grn):
    invoice["lines"][0]["quantity"] = 4
    invoice["total"] = 400
    grn["lines"][0]["quantity"] = 4


def missing_receipt_item(po, invoice, grn):
    grn["lines"] = [{"item_id": "B", "quantity": 1}]


def invalid_receipt(po, invoice, grn):
    grn["lines"][0]["quantity"] = True


def invalid_invoice_total(po, invoice, grn):
    invoice["total"] = 999


def receipt_and_invoice_over_order(po, invoice, grn):
    invoice["lines"][0]["quantity"] = 7
    invoice["total"] = 700
    grn["lines"][0]["quantity"] = 6


def currency_mismatch(po, invoice, grn):
    invoice["currency"] = "USD"


cases = [
    ("exact_match", noop, "MATCH", ()),
    ("invoice_exceeds_receipt", invoice_exceeds_receipt, "DISCREPANCY",
     ("INVOICE_EXCEEDS_RECEIVED_QUANTITY",)),
    ("receipt_exceeds_order", receipt_exceeds_order, "DISCREPANCY",
     ("RECEIPT_EXCEEDS_ORDERED_QUANTITY",)),
    ("receipt_supplier_mismatch", supplier_mismatch, "DISCREPANCY",
     ("RECEIPT_SUPPLIER_MISMATCH",)),
    ("unexpected_receipt_item", unexpected_receipt_item, "DISCREPANCY",
     ("RECEIVED_ITEM_NOT_ORDERED",)),
    ("invoice_item_replaced", invoice_item_replaced, "DISCREPANCY",
     ("INVOICE_EXCEEDS_RECEIVED_QUANTITY",
      "ITEM_MISSING_FROM_INVOICE", "UNEXPECTED_INVOICE_ITEM")),
    ("quantity_mismatch", quantity_mismatch, "DISCREPANCY",
     ("QUANTITY_MISMATCH",)),
    ("missing_receipt_item", missing_receipt_item, "DISCREPANCY",
     ("INVOICE_EXCEEDS_RECEIVED_QUANTITY",
      "RECEIVED_ITEM_NOT_ORDERED")),
    ("invalid_receipt_quantity", invalid_receipt, "NEEDS_REVIEW", ()),
    ("invalid_invoice_total", invalid_invoice_total, "NEEDS_REVIEW", ()),
    ("both_over_order", receipt_and_invoice_over_order, "DISCREPANCY",
     ("INVOICE_EXCEEDS_RECEIVED_QUANTITY", "QUANTITY_MISMATCH",
      "RECEIPT_EXCEEDS_ORDERED_QUANTITY", "TOTAL_MISMATCH")),
]

results = [
    check_three_way(name, mutate, status, codes)
    for name, mutate, status, codes in cases
]

# Currency policy is a two-document rule; verify it separately.
po, invoice, grn = documents()
currency_mismatch(po, invoice, grn)
currency_report = reconcile(po, invoice)
currency_codes = {f["code"] for f in currency_report.get("findings", [])}
currency_passed = (
    currency_report.get("status") == "DISCREPANCY"
    and "CURRENCY_MISMATCH" in currency_codes
    and "TOTAL_MISMATCH" not in currency_codes
    and "UNIT_PRICE_MISMATCH" not in currency_codes
)
results.append({
    "scenario": "currency_mismatch_policy",
    "passed": currency_passed,
    "expected_status": "DISCREPANCY",
    "actual_status": currency_report.get("status"),
    "required_findings": ["CURRENCY_MISMATCH"],
    "actual_findings": sorted(currency_codes),
})

passed = sum(result["passed"] for result in results)
total = len(results)
print(json.dumps({
    "evaluation": "DocWeave policy-hardening synthetic evaluation",
    "passed": passed,
    "total": total,
    "pass_rate": round(passed / total, 4),
    "results": results,
}, indent=2))
raise SystemExit(0 if passed == total else 1)
