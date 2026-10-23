"""Small deterministic evaluation set for the DocWeave engine."""

import json
from copy import deepcopy

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docweave.engine import reconcile


po_base = {
    "document_id": "PO-EVAL",
    "supplier_id": "SUP-1",
    "currency": "INR",
    "lines": [
        {"item_id": "A", "quantity": "2", "unit_price": "100.00"}
    ],
    "total": "200.00",
}


def pair():
    po = deepcopy(po_base)
    inv = deepcopy(po_base)
    inv["document_id"] = "INV-EVAL"
    return po, inv


cases = []


def add_case(name, expected_status, expected_codes, mutate=None):
    po, inv = pair()
    if mutate:
        mutate(po, inv)
    cases.append({
        "name": name,
        "expected_status": expected_status,
        "expected_codes": sorted(expected_codes),
        "purchase_order": po,
        "invoice": inv,
    })


add_case("exact_match", "MATCH", [])
add_case(
    "unit_price_mismatch", "DISCREPANCY",
    ["UNIT_PRICE_MISMATCH", "TOTAL_MISMATCH"],
    lambda po, inv: (
        inv["lines"][0].update(unit_price="110.00"),
        inv.update(total="220.00")
    )
)
add_case(
    "quantity_mismatch", "DISCREPANCY", ["QUANTITY_MISMATCH", "TOTAL_MISMATCH"],
    lambda po, inv: (
        inv["lines"][0].update(quantity="3"),
        inv.update(total="300.00")
    )
)
add_case(
    "supplier_mismatch", "DISCREPANCY", ["SUPPLIER_MISMATCH"],
    lambda po, inv: inv.update(supplier_id="SUP-OTHER")
)
add_case(
    "currency_mismatch", "DISCREPANCY", ["CURRENCY_MISMATCH"],
    lambda po, inv: (
        inv.update(currency="USD"),
        inv["lines"][0].update(unit_price="150.00"),
        inv.update(total="300.00")
    )
)
add_case(
    "missing_item", "DISCREPANCY", ["ITEM_MISSING_FROM_INVOICE", "UNEXPECTED_INVOICE_ITEM"],
    lambda po, inv: (
        inv["lines"].clear(),
        inv["lines"].append(
            {"item_id": "B", "quantity": "2", "unit_price": "100.00"}
        )
    )
)
# A missing or unexpected item can make declared totals inconsistent with
# the invoice lines. Use a valid total for each document so the case tests
# reconciliation rather than document validation.
cases[-1]["invoice"]["total"] = "200.00"
add_case(
    "unexpected_item", "DISCREPANCY", ["TOTAL_MISMATCH", "UNEXPECTED_INVOICE_ITEM"],
    lambda po, inv: (
        inv["lines"].append(
            {"item_id": "B", "quantity": "1", "unit_price": "10.00"}
        ),
        inv.update(total="210.00")
    )
)
add_case(
    "negative_quantity", "NEEDS_REVIEW", [],
    lambda po, inv: (
        inv["lines"][0].update(quantity="-1"),
        inv.update(total="-100.00")
    )
)
add_case(
    "declared_total_invalid", "NEEDS_REVIEW", [],
    lambda po, inv: inv.update(total="999.00")
)


results = []
passed = 0

for case in cases:
    report = reconcile(case["purchase_order"], case["invoice"])
    actual_codes = sorted(item["code"] for item in report.get("findings", []))
    ok = (
        report["status"] == case["expected_status"]
        and actual_codes == case["expected_codes"]
    )
    passed += int(ok)
    results.append({
        "case": case["name"],
        "passed": ok,
        "expected_status": case["expected_status"],
        "actual_status": report["status"],
        "expected_codes": case["expected_codes"],
        "actual_codes": actual_codes,
    })

output = {
    "evaluation": "DocWeave structured-data prototype",
    "passed": passed,
    "total": len(cases),
    "pass_rate": round(passed / len(cases), 4),
    "results": results,
}

print(json.dumps(output, indent=2))
if passed != len(cases):
    raise SystemExit(1)
