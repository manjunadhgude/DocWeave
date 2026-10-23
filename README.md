# DocWeave

Evidence-grounded business document reconciliation.

## Current scope

The first version compares structured purchase orders and invoices.
It detects supplier, currency, item, quantity, unit-price, and total
discrepancies. Invalid documents are sent to `NEEDS_REVIEW`.

This version does not extract PDFs, verify document authenticity, or
model tax, discounts, shipping, or rounding policies.

## Requirements

- Python 3.10 or later
- No third-party packages for the current version

## Run the tests

```bash
python -m unittest discover -s tests -v
```

## Reconcile the sample documents

```bash
python -m docweave.cli data/purchase_order.json data/invoice.json
```

Edit a copy of `data/invoice.json` to experiment with discrepancies.
The sample documents contain synthetic data only.
