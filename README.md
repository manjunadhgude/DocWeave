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

PDF support currently covers digital PDFs with explicitly labelled fields and
recognized pipe-separated tables. Arbitrary supplier layouts, scanned-image
OCR, visual page coordinates, document authenticity verification, tax,
discounts, shipping, currency conversion, and rounding policies are not yet
modeled. The sample documents and evaluation scenarios are synthetic.


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

## End-to-end PDF three-way reconciliation

Run extraction and three-way reconciliation from a purchase-order PDF, invoice
PDF and goods-receipt-note (GRN) PDF:

```bash
python -m docweave.pdf_three_way_cli \
  path/to/purchase_order.pdf \
  path/to/invoice.pdf \
  path/to/goods_receipt_note.pdf
```

The workflow first extracts all three documents. If any PDF is unreadable or
has missing, ambiguous or invalid required fields, the workflow returns
`NEEDS_REVIEW` and does not run reconciliation. If extraction succeeds, the
existing three-way reconciliation engine is used.

Findings retain their JSON Pointer evidence and include `pdf_evidence` with the
page number and extracted text snippet when that source location is available.
Exit code `0` means `MATCH`, `1` means a detected discrepancy, and `2` means
the workflow requires review.

This workflow inherits the conservative, labelled-field and pipe-table format
supported by the current extractor. It does not support arbitrary supplier
layouts or scanned-image OCR, and successful matching does not prove document
authenticity or physical delivery.

## FastAPI backend

Install dependencies with `python -m pip install -r requirements.txt`, then
start the local API server:

```bash
python -m uvicorn docweave.api:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` to explore the interactive API documentation.

Endpoints:

- `GET /health` — basic service health.
- `POST /api/v1/reconcile/two-way/json` — purchase order and invoice JSON.
- `POST /api/v1/reconcile/three-way/json` — purchase order, invoice and GRN JSON.
- `POST /api/v1/reconcile/three-way/pdf` — three digital PDF files.

Business results such as `MATCH`, `DISCREPANCY` and `NEEDS_REVIEW` are returned
as reconciliation reports. Invalid request shapes are rejected by the API.
The PDF endpoint applies a 25 MiB per-file limit and requires `.pdf` filenames.

This is an initial local-development API, not a production deployment.
Authentication, rate limiting, persistent job storage, deployment hardening,
and a total request-body limit at the HTTP ingress layer are not yet implemented.
Do not expose this service publicly without appropriate security controls.

## Persistent reconciliation history

Batch 11 adds a database-backed history of reconciliation results. The API
saves each successful reconciliation operation, including `MATCH`,
`DISCREPANCY`, and `NEEDS_REVIEW` reports. Original JSON documents and original
PDF files are not stored. PDF source metadata retains available fingerprints
and basic provenance fields, without temporary filesystem paths.

By default, the API uses a local SQLite database at `./docweave.db`. This is a
convenient local-development fallback. To use PostgreSQL, configure the
`DATABASE_URL` environment variable with a SQLAlchemy PostgreSQL URL using
psycopg 3, for example:

`postgresql+psycopg://docweave:YOUR_PASSWORD@127.0.0.1:5432/docweave`

A local PostgreSQL service can be started with Docker Compose. Copy
`.env.example` to `.env`, replace the example password in both environment
values with the same URL-safe local-development password, and then run:

```bash
docker compose up -d db
```

In the terminal where you will run the API, load the environment values and
start the service:

```bash
set -a
source .env
set +a
python -m uvicorn docweave.api:app --host 127.0.0.1 --port 8000
```

Database schema changes are managed with Alembic migrations. The API does
not create or upgrade tables automatically at startup.

For a new database, apply the checked-in migrations before starting the API:

```bash
python -m alembic upgrade head
```

For an existing database created by an earlier DocWeave version, back it up
first, set `DATABASE_URL` to that exact database, and run the read-only schema
verification command:

```bash
python tools/verify_database_schema.py
```

Only if verification succeeds should you mark the existing schema as the
initial migration version:

```bash
python -m alembic stamp head
```

Stamping records the migration version without creating, dropping or altering
application tables. Do not stamp a database whose schema has not been verified.
Future schema changes should be added as new migrations. Review and test
migrations against backups before production use.

History endpoints:

- `GET /api/v1/reconciliations` — list saved records, newest first.
- `GET /api/v1/reconciliations?status=MATCH` — filter by result status.
- `GET /api/v1/reconciliations?workflow=two_way_json` — filter by workflow.
- `GET /api/v1/reconciliations?limit=20&offset=0` — paginate history.
- `GET /api/v1/reconciliations/{reconciliation_id}` — retrieve a saved report.

Every reconciliation POST response now includes `reconciliation_id` and
`created_at`. The history listing returns metadata; the detail endpoint
returns the saved report. A database write failure returns an error rather
than claiming the result was saved.

The default SQLite database is intended for local development. Automated API
tests use a separate SQLite test database. PostgreSQL compatibility is
implemented, but a real PostgreSQL integration run is still required before
claiming that deployment has been validated against a live PostgreSQL server.


## Idempotent API retries

Reconciliation POST endpoints optionally accept an `Idempotency-Key` header.
Use the same key when retrying the same logical submission after a timeout or
uncertain network response. A matching retry returns the original saved response
and does not create another history record.

Keys are scoped to the workflow. Reusing a key in the same workflow with
different input returns HTTP `409 Conflict`; use a new key for a new submission.
Keys must be 1–128 characters and contain only letters, digits, periods,
underscores, colons or hyphens.

The API stores the key, request fingerprint and original response in a separate
database table. The database uniqueness constraint and transaction protect
against concurrent duplicate submissions. Requests without the header retain
the previous behavior. This feature does not replace authentication, rate
limiting, request-size controls at the HTTP ingress, or production migrations.
