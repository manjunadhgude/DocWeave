"""Conservative field extraction for a documented, pipe-table PDF layout.

This is not a general-purpose document-understanding model. It extracts only
explicitly labelled fields and table rows whose columns can be identified.
Every accepted value retains page-level text evidence.
"""

import re
from decimal import Decimal, InvalidOperation

from docweave.pdf_ingest import extract_pdf_text


DOCUMENT_LABELS = (
    r"Document ID|Invoice Number|Invoice No\.?|Invoice ID|"
    r"Purchase Order Number|Purchase Order No\.?|PO Number|PO No\.?|"
    r"GRN Number|GRN No\.?|Receipt Number"
)
SUPPLIER_LABELS = r"Supplier ID|Supplier Code|Vendor ID|Vendor Code"
TOTAL_LABELS = r"Grand Total|Invoice Total|Total Amount|Total Due|Amount Due|Total"

NUMBER_PATTERN = re.compile(r"^\d+(?:\.\d+)?$")


class PDFFieldExtractionError(ValueError):
    """Raised when PDF text cannot be extracted for field processing."""


def _evidence(line):
    return {
        "page_number": line["page_number"],
        "snippet": line["text"].strip()[:300],
    }


def _lines_from_pages(pages):
    lines = []
    for page in pages:
        for raw_line in page["text"].splitlines():
            text = raw_line.strip()
            if text:
                lines.append({
                    "page_number": page["page_number"],
                    "text": text,
                })
    return lines


def _scalar(lines, pattern, field_name, reasons):
    """Extract one explicitly labelled value; conflicting values need review."""
    matches = []
    regex = re.compile(pattern, re.IGNORECASE)

    for line in lines:
        match = regex.match(line["text"])
        if match:
            value = match.group(1).strip()
            if value:
                matches.append({
                    "value": value,
                    "evidence": _evidence(line),
                })

    unique = {}
    for item in matches:
        unique.setdefault(item["value"], item)

    if not unique:
        reasons.append(f"MISSING_FIELD:{field_name}")
        return {"value": None, "evidence": None, "candidates": []}

    if len(unique) > 1:
        reasons.append(f"AMBIGUOUS_FIELD:{field_name}")
        return {
            "value": None,
            "evidence": None,
            "candidates": list(unique.values()),
        }

    item = next(iter(unique.values()))
    return {
        "value": item["value"],
        "evidence": item["evidence"],
        "candidates": [],
    }


def _column_index(header, aliases):
    normalized = re.sub(r"\s+", " ", header.strip().lower())
    return 0 if normalized in aliases else None


def _find_column(headers, aliases):
    for index, header in enumerate(headers):
        if _column_index(header, aliases) is not None:
            return index
    return None


def _extract_lines(lines, role, reasons):
    """Read rows only after finding a recognizable pipe-separated header."""
    item_aliases = {"item id", "item code", "product id", "sku"}
    quantity_aliases = {"quantity", "qty", "received quantity", "received qty"}
    price_aliases = {"unit price", "unit cost", "price per unit"}

    header_info = None
    for index, line in enumerate(lines):
        if "|" not in line["text"]:
            continue
        headers = [part.strip() for part in line["text"].split("|")]
        item_col = _find_column(headers, item_aliases)
        qty_col = _find_column(headers, quantity_aliases)
        price_col = _find_column(headers, price_aliases)

        if item_col is not None and qty_col is not None:
            if role == "goods_receipt_note" or price_col is not None:
                header_info = (index, len(headers), item_col, qty_col, price_col)
                break

    if header_info is None:
        reasons.append("MISSING_OR_UNRECOGNIZED_LINE_ITEM_TABLE")
        return []

    header_index, width, item_col, qty_col, price_col = header_info
    found = []
    for line in lines[header_index + 1:]:
        text = line["text"]
        if "|" not in text:
            continue

        # Markdown/PDF table separator rows contain only dashes, spaces or colons.
        if re.fullmatch(r"[\s|:-]+", text):
            continue

        cells = [part.strip() for part in text.split("|")]
        if len(cells) != width:
            continue
        if max(item_col, qty_col, price_col if price_col is not None else 0) >= len(cells):
            continue

        item_id = cells[item_col]
        quantity = cells[qty_col]
        unit_price = cells[price_col] if price_col is not None else None

        if not item_id or item_id.lower() in item_aliases:
            continue

        entry = {
            "item_id": item_id,
            "quantity": quantity,
            "evidence": _evidence(line),
        }
        if role != "goods_receipt_note":
            entry["unit_price"] = unit_price
        found.append(entry)

    if not found:
        reasons.append("MISSING_LINE_ITEM_ROWS")
        return []

    seen = set()
    for item in found:
        if item["item_id"] in seen:
            reasons.append(f"DUPLICATE_ITEM_ID:{item['item_id']}")
        seen.add(item["item_id"])

        if not NUMBER_PATTERN.fullmatch(item["quantity"]):
            reasons.append(f"INVALID_QUANTITY:{item['item_id']}")
        else:
            try:
                if Decimal(item["quantity"]) <= 0:
                    reasons.append(f"INVALID_QUANTITY:{item['item_id']}")
            except InvalidOperation:
                reasons.append(f"INVALID_QUANTITY:{item['item_id']}")

        if role != "goods_receipt_note":
            if not item["unit_price"] or not NUMBER_PATTERN.fullmatch(item["unit_price"]):
                reasons.append(f"INVALID_UNIT_PRICE:{item['item_id']}")
            else:
                try:
                    if Decimal(item["unit_price"]) < 0:
                        reasons.append(f"INVALID_UNIT_PRICE:{item['item_id']}")
                except InvalidOperation:
                    reasons.append(f"INVALID_UNIT_PRICE:{item['item_id']}")

    return found


def extract_pdf_fields(path, role):
    """Return extracted fields, evidence and review reasons from a digital PDF.

    Supported roles: purchase_order, invoice, goods_receipt_note.
    A document object is returned only when all required checks pass.
    """
    allowed_roles = {"purchase_order", "invoice", "goods_receipt_note"}
    if role not in allowed_roles:
        raise ValueError(f"Unsupported document role: {role}")

    extracted, source = extract_pdf_text(path, role)
    lines = _lines_from_pages(extracted["pages"])
    reasons = []

    document_id = _scalar(
        lines,
        rf"^\s*(?:{DOCUMENT_LABELS})\s*[:#=-]\s*(.*?)\s*$",
        "document_id",
        reasons,
    )
    supplier_id = _scalar(
        lines,
        rf"^\s*(?:{SUPPLIER_LABELS})\s*[:#=-]\s*(.*?)\s*$",
        "supplier_id",
        reasons,
    )

    fields = {
        "document_id": document_id,
        "supplier_id": supplier_id,
    }

    if role != "goods_receipt_note":
        currency = _scalar(
            lines,
            r"^\s*Currency\s*[:#=-]\s*([A-Z]{3})\s*$",
            "currency",
            reasons,
        )
        if currency["value"] is not None:
            currency["value"] = currency["value"].upper()
            if not re.fullmatch(r"[A-Z]{3}", currency["value"]):
                reasons.append("INVALID_CURRENCY")
                currency["value"] = None
        fields["currency"] = currency

        total = _scalar(
            lines,
            rf"^\s*(?:{TOTAL_LABELS})\s*[:#=-]\s*(?:(?:[A-Z]{{3}})\s*)?([0-9]+(?:\.[0-9]+)?)\s*$",
            "total",
            reasons,
        )
        fields["total"] = total
        if total["value"] is not None:
            try:
                if Decimal(total["value"]) < 0:
                    reasons.append("INVALID_TOTAL")
            except InvalidOperation:
                reasons.append("INVALID_TOTAL")

    line_items = _extract_lines(lines, role, reasons)

    # Construct the normalized schema expected by the existing engine.
    document = {
        "document_id": fields["document_id"]["value"],
        "supplier_id": fields["supplier_id"]["value"],
        "lines": [],
    }
    if role != "goods_receipt_note":
        document["currency"] = fields["currency"]["value"]
        document["total"] = fields["total"]["value"]

    for item in line_items:
        normalized = {
            "item_id": item["item_id"],
            "quantity": item["quantity"],
        }
        if role != "goods_receipt_note":
            normalized["unit_price"] = item["unit_price"]
        document["lines"].append(normalized)

    # A complete extraction is not automatically proof that the document is
    # genuine. It means only that the supported fields were read unambiguously.
    status = "NEEDS_REVIEW" if reasons else "EXTRACTED"

    return {
        "status": status,
        "source": source,
        "fields": fields,
        "line_items": line_items,
        "review_reasons": sorted(set(reasons)),
        "document": document if status == "EXTRACTED" else None,
        "limitations": [
            "Only explicitly labelled fields and recognized pipe-table layouts are supported.",
            "This is rule-based extraction, not general PDF understanding.",
            "Evidence is a page number and extracted text snippet, not a visual PDF coordinate.",
            "Text extraction can miss content or reorder text; scanned PDFs may require OCR.",
            "A successful extraction does not establish authenticity or physical delivery.",
        ],
    }
