# DocWeave Portfolio Demo

DocWeave reconciles purchase orders, supplier invoices and goods receipt notes
using deterministic business rules, traceable evidence, and conservative review
handling. It also includes a retrieval-augmented generation (RAG) prototype.

## Structured-data demo

```bash
python -m docweave.cli data/purchase_order.json data/invoice.json
python -m docweave.three_way_cli data/purchase_order.json data/invoice.json data/goods_receipt_note.json
python -m unittest discover -s tests -v
python tools/evaluate.py
python tools/evaluate_three_way.py
python tools/evaluate_rag.py
python tools/evaluate_rag_expanded.py
```

## PDF demo

```bash
python -m docweave.pdf_cli path/to/invoice.pdf --role invoice
python -m docweave.pdf_fields_cli path/to/invoice.pdf --role invoice
```

PDF extraction supports specific labelled layouts, not arbitrary supplier
formats. Scanned PDFs require configured OCR dependencies and Tesseract.

## API demo

```bash
export DOCWEAVE_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m uvicorn docweave.api:app --host 127.0.0.1 --port 8000
```

Explore http://127.0.0.1:8000/docs. Protected API calls require a Bearer token.

## Interview narrative

1. Deterministic rules handle business truth rather than delegating it to an LLM.
2. Ambiguous or invalid input is routed to review.
3. Findings preserve source evidence and provenance.
4. RAG retrieves evidence chunks and associates answers with citations.
5. Tests and synthetic evaluations make behavior reproducible.

## Limitations

MATCH means configured fields agree; it does not prove document authenticity
or physical delivery. Synthetic metrics are not real-world accuracy. Citation
matching is not semantic entailment verification. OCR, semantic retrieval and
real-LLM answer quality require separate evaluation.
