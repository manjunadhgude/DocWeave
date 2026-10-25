"""Evidence-grounded three-way PO, invoice and receipt matching."""

from decimal import Decimal, DecimalException

from docweave.engine import DocumentError, _decimal, _evidence, _money, reconcile, _validate


def _validate_receipt(document):
    label = "goods_receipt_note"
    if not isinstance(document, dict):
        raise DocumentError(f"{label} must be a JSON object")

    for field in ("document_id", "supplier_id"):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DocumentError(f"{label}.{field} is required")

    lines = document.get("lines")
    if not isinstance(lines, list) or not lines:
        raise DocumentError(f"{label}.lines must be a non-empty list")

    validated = {}
    for index, line in enumerate(lines):
        prefix = f"{label}.lines[{index}]"
        if not isinstance(line, dict):
            raise DocumentError(f"{prefix} must be an object")

        item = line.get("item_id")
        if not isinstance(item, str) or not item.strip():
            raise DocumentError(f"{prefix}.item_id is required")
        if item in validated:
            raise DocumentError(f"{label} contains duplicate item_id {item!r}")

        quantity = _decimal(line.get("quantity"), f"{prefix}.quantity")
        if quantity <= 0:
            raise DocumentError(f"{prefix}.quantity must be positive")

        validated[item] = {"index": index, "quantity": quantity}

    return {
        "document_id": document["document_id"],
        "supplier_id": document["supplier_id"],
        "lines": validated,
    }


def reconcile_three_way(purchase_order, invoice, goods_receipt_note):
    """Return a JSON-ready reconciliation report for three business documents."""
    try:
        receipt = _validate_receipt(goods_receipt_note)
    except (DocumentError, DecimalException) as error:
        report = reconcile(purchase_order, invoice)
        report["goods_receipt_note_id"] = (
            goods_receipt_note.get("document_id")
            if isinstance(goods_receipt_note, dict) else None
        )
        report["status"] = "NEEDS_REVIEW"
        report["reason"] = f"Invalid goods receipt note: {error}"
        return report

    report = reconcile(purchase_order, invoice)
    report["goods_receipt_note_id"] = receipt["document_id"]

    # Invalid PO/invoice data must remain a review case.
    if report["status"] == "NEEDS_REVIEW":
        return report

    po = _validate(purchase_order, "purchase_order")
    inv = _validate(invoice, "invoice")

    # In three-way matching, a lower invoice quantity can be legitimate when
    # it matches the quantity actually received. Likewise, an ordered item
    # absent from both the invoice and receipt may simply be pending delivery.
    # Keep the two-way engine strict; apply these exceptions only here, where
    # receipt evidence is available.
    findings = []
    for finding in report["findings"]:
        code = finding.get("code")
        field = finding.get("field", "")
        item = field.removeprefix("lines.").split(".", 1)[0]
        if code == "ITEM_MISSING_FROM_INVOICE" and item not in receipt["lines"]:
            continue
        if code == "TOTAL_MISMATCH":
            # The PO total describes the full order, while an invoice may cover
            # only the delivered portion. Suppress this finding only when every
            # invoiced line is ordered, priced as agreed, and matches receipt
            # quantities; the invoice validator has already checked its total.
            invoice_is_receipt_supported = all(
                invoice_item in po["lines"]
                and invoice_line["unit_price"]
                == po["lines"][invoice_item]["unit_price"]
                and invoice_item in receipt["lines"]
                and invoice_line["quantity"]
                == receipt["lines"][invoice_item]["quantity"]
                and invoice_line["quantity"]
                <= po["lines"][invoice_item]["quantity"]
                for invoice_item, invoice_line in inv["lines"].items()
            )
            if invoice_is_receipt_supported:
                continue
        findings.append(finding)
    report["findings"] = findings

    def add(code, field, expected, actual, explanation, ev_expected, ev_actual):
        findings.append({
            "code": code,
            "field": field,
            "expected": expected,
            "actual": actual,
            "explanation": explanation,
            "evidence": {"expected": ev_expected, "actual": ev_actual},
        })

    if receipt["supplier_id"] != po["supplier_id"]:
        add(
            "RECEIPT_SUPPLIER_MISMATCH", "supplier_id",
            po["supplier_id"], receipt["supplier_id"],
            "The receipt supplier differs from the purchase-order supplier.",
            _evidence("purchase_order", po, "/supplier_id", po["supplier_id"]),
            _evidence(
                "goods_receipt_note", receipt,
                "/supplier_id", receipt["supplier_id"],
            ),
        )

    po_items = set(po["lines"])
    inv_items = set(inv["lines"])
    grn_items = set(receipt["lines"])

    for item in sorted(grn_items - po_items):
        line = receipt["lines"][item]
        add(
            "RECEIVED_ITEM_NOT_ORDERED", f"lines.{item}",
            None, item,
            "The receipt includes an item absent from the purchase order.",
            None,
            _evidence(
                "goods_receipt_note", receipt,
                f"/lines/{line['index']}/item_id", item,
            ),
        )

    # An invoice must not bill more units than the receipt records.
    # Missing receipt items are treated as zero recorded units.
    for item in sorted(inv_items):
        billed = inv["lines"][item]
        received = receipt["lines"].get(item)
        received_qty = (
            received["quantity"] if received else Decimal("0")
        )
        if billed["quantity"] > received_qty:
            expected_evidence = (
                _evidence(
                    "goods_receipt_note", receipt,
                    f"/lines/{received['index']}/quantity", received_qty,
                )
                if received else
                _evidence("goods_receipt_note", receipt, "/lines", None)
            )
            add(
                "INVOICE_EXCEEDS_RECEIVED_QUANTITY",
                f"lines.{item}.quantity",
                _money(received_qty), _money(billed["quantity"]),
                "The invoice bills more units than the receipt records. "
                "Verify delivery evidence before approving payment.",
                expected_evidence,
                _evidence(
                    "invoice", inv,
                    f"/lines/{billed['index']}/quantity", billed["quantity"],
                ),
            )

    for item in sorted(po_items & grn_items):
        ordered = po["lines"][item]
        received = receipt["lines"][item]
        if received["quantity"] > ordered["quantity"]:
            add(
                "RECEIPT_EXCEEDS_ORDERED_QUANTITY",
                f"lines.{item}.quantity",
                _money(ordered["quantity"]), _money(received["quantity"]),
                "The receipt records more units than the purchase order. "
                "Verify an amended order or authorized over-delivery.",
                _evidence(
                    "purchase_order", po,
                    f"/lines/{ordered['index']}/quantity",
                    ordered["quantity"],
                ),
                _evidence(
                    "goods_receipt_note", receipt,
                    f"/lines/{received['index']}/quantity",
                    received["quantity"],
                ),
            )

    report["status"] = "DISCREPANCY" if findings else "MATCH"
    report.setdefault("summary", {})["goods_receipt_quantities"] = {
        item: _money(line["quantity"])
        for item, line in sorted(receipt["lines"].items())
    }
    report.setdefault("limitations", []).append(
        "Three-way matching uses structured JSON and cannot verify physical "
        "delivery or document authenticity. Partial deliveries can be valid; "
        "delivery schedules, returns, tolerances and order amendments are not modeled."
    )
    return report
