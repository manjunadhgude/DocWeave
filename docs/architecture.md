# DocWeave Architecture

## Purpose and scope

DocWeave is a document-processing and reconciliation prototype. It supports structured-data reconciliation, PDF intake/extraction, three-way purchase-order/invoice/goods-receipt reconciliation, an HTTP API, persistent reconciliation history, and an optional retrieval-augmented generation (RAG) path. It is not represented as a production-certified financial or compliance system.

## High-level components

- **Structured ingestion and validation** — `docweave/ingest.py` reads and validates structured input, including invalid encodings, duplicate JSON keys, invalid roots, and non-standard numeric values.
- **Reconciliation engine** — `docweave/engine.py` implements structured comparison and policy decisions.
- **Three-way reconciliation** — `docweave/three_way.py` compares purchase-order, invoice, and goods-receipt data and reports policy-defined mismatches.
- **PDF workflows** — `docweave/pdf_ingest.py`, `docweave/pdf_fields.py`, `docweave/pdf_ocr.py`, and `docweave/pdf_three_way.py` implement PDF intake, field extraction, optional OCR, and three-way PDF workflows. Extraction results require review; extracted text is not proof that a document is authentic.
- **HTTP API** — `docweave/api.py` exposes API routes, authentication checks, upload-size limits, reconciliation workflows, and storage-backed operations.
- **Persistence** — `docweave/storage.py` defines SQLAlchemy storage configuration and ORM metadata. `alembic/` contains schema migration configuration and migration scripts. The configured database is selected through `DATABASE_URL`; absent that variable, the code defaults to SQLite. PostgreSQL is configured in `compose.yaml`.
- **RAG** — `docweave/rag/` contains ingestion, embeddings, retrieval, providers, and answer generation. `docweave/rag/answering.py` includes conservative evidence-support checks. These checks are safeguards, not a general proof of semantic correctness.
- **Evaluation and tests** — `tests/` contains automated tests. `tools/evaluate*.py` provides synthetic evaluation harnesses, and `tools/portfolio_smoke.sh` runs a portfolio-oriented smoke test.

## Main data flows

### Reconciliation

1. Input records are ingested and validated.
2. The reconciliation engine compares relevant fields under explicit policies.
3. Three-way workflows compare purchase-order, invoice, and goods-receipt information.
4. The API can expose these workflows and persist reconciliation history through the storage layer.
5. Results should be interpreted as agreement or disagreement between supplied records, not independent proof of authenticity, delivery, or payment.

### PDF processing

1. PDF input is checked against configured intake limits and basic file constraints.
2. Text is extracted and/or OCR is used when configured and available.
3. Field extraction produces candidate structured values.
4. Reconciliation policies compare extracted values.
5. Low-confidence or ambiguous extraction should be reviewed by a person; OCR output can contain errors.

### Retrieval-augmented generation

1. Documents are ingested into the RAG pipeline.
2. Retrieval selects candidate evidence chunks using configured retrieval methods.
3. The answer pipeline uses retrieved evidence and conservative support checks to decide whether to answer or abstain.
4. Evaluation scripts report retrieval/decision metrics on their configured datasets.

RAG evaluation results must be described with the dataset scope. Synthetic benchmark success does not establish real-world semantic accuracy, complete contradiction handling, or hallucination-free generation.

## Runtime and configuration

- Python dependencies are declared in `requirements.txt`.
- API configuration and authentication are implemented in `docweave/api.py`; configure required secrets through environment variables or an ignored local environment file. Never commit secrets.
- `compose.yaml` defines a PostgreSQL 17 service and a named data volume. The service requires `POSTGRES_PASSWORD`.
- Alembic uses `DATABASE_URL` when provided and otherwise falls back to the URL in `alembic.ini`. The default configuration is SQLite; PostgreSQL must be explicitly configured and verified.
- Demo steps are documented in `docs/PORTFOLIO_DEMO.md`; general setup and current limitations are documented in `README.md`.

## Security and operational boundaries

The code includes bearer-token authentication checks and request/upload size controls. These are important safeguards, but they do not constitute a complete security audit. Before production use, independently verify authorization policy, secret management, network exposure, dependency vulnerabilities, upload/content validation, file-system isolation, logging/error disclosure, database permissions, backups, monitoring, and recovery procedures.

Do not expose PostgreSQL publicly without appropriate network controls. The supplied Compose configuration binds the database port to loopback. Keep credentials out of source control and logs.

## Verification status and limitations

The finalization script records actual test, evaluation, migration, and schema-check outcomes in a timestamped report under `.docweave-portfolio/closeout-*/`. Read that report before claiming database verification.

- Automated tests establish only the behaviors they exercise.
- Synthetic reconciliation and RAG benchmarks are not substitutes for representative, permission-cleared real documents and independently reviewed expected answers.
- PostgreSQL readiness and migration success alone do not prove every API persistence workflow or transaction/recovery behavior.
- PDF text extraction/OCR does not verify document authenticity.
- Numeric grounding checks are conservative and may reject valid derived values; they do not establish full claim-level grounding.
- Production readiness and security certification are not claimed by this document.

## Suggested reviewer walkthrough

1. Follow the setup and test instructions in `README.md`.
2. Run the structured and three-way reconciliation examples.
3. Run the PDF demo in `docs/PORTFOLIO_DEMO.md`.
4. Run the API demo with a locally configured token.
5. Review the generated evaluation reports and explicitly discuss dataset size, synthetic cases, known failures, and unverified behavior.
6. If using PostgreSQL, verify the database and migrations in the close-out report before claiming that backend configuration is operational.
