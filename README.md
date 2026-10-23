# DocWeave

Evidence-grounded business document reconciliation.

## Current scope

The structured-data prototype compares purchase orders and supplier invoices.
It detects supplier, currency, item, quantity, unit-price, and total
discrepancies. Invalid inputs are sent to `NEEDS_REVIEW`.

Each discrepancy includes expected and actual values and, when a value exists,
a JSON Pointer identifying its source location. The CLI also reports input
filenames, byte sizes, and SHA-256 fingerprints.

The hash helps identify the exact file used; it does not prove who created the
file or that the business document is authentic.

## Requirements

- Python 3.10 or later
- Python standard library
- `pypdf` for digital PDF text extraction

Install dependencies with `python -m pip install -r requirements.txt`.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## Run the evaluation

```bash
python tools/evaluate.py
```

## Reconcile the sample documents

```bash
python -m docweave.cli data/purchase_order.json data/invoice.json
```

The CLI returns JSON. Exit code `0` means `MATCH`, `1` means a discrepancy or
review outcome, and `2` means an input or command error.

## Current limitations

This version reads structured JSON only. It does not extract PDFs, provide PDF
page coordinates, verify authenticity, or model tax, discounts, shipping,
currency conversion, or rounding policies. The sample documents are synthetic.


## Three-way reconciliation

Compare a purchase order, supplier invoice and goods receipt note (GRN):

```bash
python -m docweave.three_way_cli \
  data/purchase_order.json data/invoice.json data/goods_receipt_note.json
```

The GRN records a document ID, supplier ID, item IDs and received quantities.
DocWeave flags invoices that bill more than recorded receipt quantities,
receipts that exceed ordered quantities, unexpected received items and supplier
mismatches. Findings include JSON Pointer evidence and source fingerprints.

Run the full tests and synthetic evaluation with:

```bash
python -m unittest discover -s tests -v
python tools/evaluate_three_way.py
```

The synthetic evaluation tests designed scenarios only; it is not a claim of
production accuracy. Partial deliveries may be valid, and delivery schedules,
returns, tolerances and amended orders are not yet modeled.

## Reconciliation policy boundaries

- `MATCH` means the structured fields checked by the current rules agree; it
  does not prove that a document is genuine or that goods physically arrived.
- `DISCREPANCY` means one or more configured checks found a difference.
  Business users should review the evidence before deciding what action to take.
- `NEEDS_REVIEW` is used when input data is invalid or cannot be safely checked.
- Currency differences are reported, but monetary amounts are not directly
  compared across different currencies.
- In three-way matching, an invoice quantity greater than the recorded receipt
  is flagged. A receipt quantity greater than the order is separately flagged.
- A partial delivery can be legitimate. However, the current policy still flags
  invoice-versus-order quantity or total differences, even if the invoice matches
  the quantity received. Such cases need review; partial-invoice approval rules
  have not yet been implemented.
- A missing item in the receipt is treated as zero recorded quantity for the
  overbilling check. The evidence points to the receipt's `lines` collection to
  show that no matching line was found.
- Synthetic evaluation cases are designed checks, not real-world accuracy
  measurements. Real supplier documents and expert-reviewed expected outcomes
  are needed before making claims about production performance.

Run the expanded evaluation with:

```bash
python tools/evaluate_three_way.py
```

Run all tests, including policy-hardening cases, with:

```bash
python -m unittest discover -s tests -v
```

## Digital PDF text extraction

Install the PDF dependency:

```bash
python -m pip install -r requirements.txt
```

Extract text from a digital PDF, preserving page numbers and a fingerprint
of the source file:

```bash
python -m docweave.pdf_cli path/to/invoice.pdf --role invoice
```

Supported roles are `purchase_order`, `invoice`, and `goods_receipt_note`.
The command returns JSON containing each page's extracted text, page number,
character count, and source metadata including SHA-256.

The current extractor has a 25 MiB file-size limit and a 200-page limit.
Encrypted, invalid, or textless PDFs are sent to review with a structured
error. A textless PDF may be scanned and require OCR. PDF text extraction
does not yet identify business fields or feed the reconciliation engine.
Extracted text order and completeness depend on the PDF's internal structure.

Test the PDF ingestion feature with:

```bash
python -m unittest tests.test_pdf_ingest -v
```

## Conservative PDF field extraction

Extract labelled fields from a supported digital PDF layout:

```bash
python -m docweave.pdf_fields_cli path/to/invoice.pdf --role invoice
python -m docweave.pdf_fields_cli path/to/purchase_order.pdf --role purchase_order
python -m docweave.pdf_fields_cli path/to/grn.pdf --role goods_receipt_note
```

The first supported layout uses explicit labels such as `Invoice No: INV-1`,
`Supplier ID: SUP-1`, `Currency: INR`, and `Grand Total: 100.00`, followed by
a pipe-separated line-item table. The table needs recognizable columns such as
`Item ID`, `Quantity`, and, for invoices/purchase orders, `Unit Price`.
GRNs need an item ID and received quantity.

Each extracted field and line item includes the page number and a snippet from
the extracted PDF text. Missing or conflicting values, unrecognized tables,
duplicate item IDs, and invalid quantities/prices produce `NEEDS_REVIEW`.
When review is required, the normalized `document` is withheld so incomplete
data is not accidentally sent to reconciliation.

This is a controlled-layout, rule-based first step, not general PDF
understanding. It does not yet locate visual page coordinates, handle arbitrary
supplier templates, perform OCR, or feed PDF results automatically into the
reconciliation CLI. A successful extraction is not proof of authenticity.
