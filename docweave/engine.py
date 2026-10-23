"""Deterministic reconciliation of structured purchase orders and invoices."""

from decimal import Decimal, DecimalException, InvalidOperation


class DocumentError(ValueError):
    """Raised when a document cannot be validated."""


def _decimal(value, field):
    if isinstance(value, bool) or value is None:
        raise DocumentError(f"{field} must be a valid decimal number")
    try:
        number = Decimal(str(value))
    except (DecimalException, ValueError, TypeError):
        raise DocumentError(f"{field} must be a valid decimal number") from None
    if not number.is_finite():
        raise DocumentError(f"{field} must be finite")
    return number


def _validate(document, label):
    if not isinstance(document, dict):
        raise DocumentError(f"{label} must be a JSON object")

    for field in ("document_id", "supplier_id", "currency"):
        value = document.get(field)
        if not isinstance(value, str) or not value.strip():
            raise DocumentError(f"{label}.{field} is required")

    lines = document.get("lines")
    if not isinstance(lines, list) or not lines:
        raise DocumentError(f"{label}.lines must be a non-empty list")

    validated = {}
    try:
        for index, line in enumerate(lines):
            prefix = f"{label}.lines[{index}]"
            if not isinstance(line, dict):
                raise DocumentError(f"{prefix} must be an object")

            item = line.get("item_id")
            if not isinstance(item, str) or not item.strip():
                raise DocumentError(f"{prefix}.item_id is required")
            if item in validated:
                raise DocumentError(
                    f"{label} contains duplicate item_id {item!r}"
                )

            quantity = _decimal(line.get("quantity"), f"{prefix}.quantity")
            price = _decimal(line.get("unit_price"), f"{prefix}.unit_price")
            if quantity <= 0:
                raise DocumentError(f"{prefix}.quantity must be positive")
            if price < 0:
                raise DocumentError(f"{prefix}.unit_price cannot be negative")

            validated[item] = {
                "quantity": quantity,
                "unit_price": price,
                "line_total": quantity * price,
            }

        declared_total = _decimal(document.get("total"), f"{label}.total")
        if declared_total < 0:
            raise DocumentError(f"{label}.total cannot be negative")

        calculated_total = sum(
            (line["line_total"] for line in validated.values()), Decimal("0")
        )
    except DecimalException:
        raise DocumentError(
            f"{label} contains values outside supported decimal arithmetic limits"
        ) from None

    if declared_total != calculated_total:
        raise DocumentError(
            f"{label}.total is {declared_total}, but its lines sum to "
            f"{calculated_total}"
        )

    return {
        "document_id": document["document_id"],
        "supplier_id": document["supplier_id"],
        "currency": document["currency"],
        "lines": validated,
        "total": declared_total,
    }


def _money(value):
    return format(value, "f")


def reconcile(purchase_order, invoice):
    """Return a JSON-ready reconciliation report."""
    base = {
        "purchase_order_id": (
            purchase_order.get("document_id")
            if isinstance(purchase_order, dict) else None
        ),
        "invoice_id": (
            invoice.get("document_id")
            if isinstance(invoice, dict) else None
        ),
        "findings": [],
    }

    try:
        po = _validate(purchase_order, "purchase_order")
        inv = _validate(invoice, "invoice")
    except DocumentError as error:
        base.update({"status": "NEEDS_REVIEW", "reason": str(error)})
        return base

    findings = base["findings"]

    def finding(code, field, expected, actual, explanation):
        findings.append({
            "code": code,
            "field": field,
            "expected": expected,
            "actual": actual,
            "explanation": explanation,
        })

    if po["supplier_id"] != inv["supplier_id"]:
        finding(
            "SUPPLIER_MISMATCH", "supplier_id",
            po["supplier_id"], inv["supplier_id"],
            "The supplier identifiers differ."
        )

    same_currency = po["currency"] == inv["currency"]
    if not same_currency:
        finding(
            "CURRENCY_MISMATCH", "currency",
            po["currency"], inv["currency"],
            "The document currencies differ; monetary values cannot be "
            "compared directly without an explicit conversion policy."
        )

    po_items = set(po["lines"])
    inv_items = set(inv["lines"])

    for item in sorted(po_items - inv_items):
        finding(
            "ITEM_MISSING_FROM_INVOICE", f"lines.{item}",
            item, None, "The purchase-order item is absent from the invoice."
        )

    for item in sorted(inv_items - po_items):
        finding(
            "UNEXPECTED_INVOICE_ITEM", f"lines.{item}",
            None, item, "The invoice contains an item absent from the purchase order."
        )

    for item in sorted(po_items & inv_items):
        expected = po["lines"][item]
        actual = inv["lines"][item]

        if expected["quantity"] != actual["quantity"]:
            finding(
                "QUANTITY_MISMATCH", f"lines.{item}.quantity",
                _money(expected["quantity"]), _money(actual["quantity"]),
                "The invoiced quantity differs from the ordered quantity."
            )

        # Prices are comparable only when both documents use the same currency.
        if same_currency and expected["unit_price"] != actual["unit_price"]:
            finding(
                "UNIT_PRICE_MISMATCH", f"lines.{item}.unit_price",
                _money(expected["unit_price"]), _money(actual["unit_price"]),
                "The invoiced unit price differs from the agreed unit price."
            )

    if same_currency and po["total"] != inv["total"]:
        finding(
            "TOTAL_MISMATCH", "total",
            _money(po["total"]), _money(inv["total"]),
            "The declared document totals differ."
        )

    base.update({
        "status": "DISCREPANCY" if findings else "MATCH",
        "findings": findings,
        "summary": {
            "purchase_order_total": _money(po["total"]),
            "invoice_total": _money(inv["total"]),
            "currency": po["currency"] if same_currency else None,
        },
        "limitations": [
            "Only structured data is checked; source-document evidence and "
            "authenticity are not verified.",
            "Tax, discounts, shipping, currency conversion and rounding "
            "policies are not modeled.",
        ],
    })
    return base
