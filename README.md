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
- Python standard library only

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
