"""Connect conservative PDF extraction to existing three-way reconciliation."""

from docweave.pdf_ingest import PDFLoadError
from docweave.pdf_fields import extract_pdf_fields
from docweave.three_way import reconcile_three_way


ROLES = ("purchase_order", "invoice", "goods_receipt_note")


def _evidence_index(extraction):
    """Map normalized JSON paths to the PDF page/snippet that supplied them."""
    result = {}
    fields = extraction["fields"]

    for field_name, field in fields.items():
        if field.get("evidence"):
            result[f"/{field_name}"] = field["evidence"]

    for index, item in enumerate(extraction["line_items"]):
        for field_name in ("item_id", "quantity", "unit_price"):
            if field_name in item and item.get("evidence"):
                result[f"/lines/{index}/{field_name}"] = item["evidence"]

    return result


def reconcile_pdf_documents(
    purchase_order_pdf, invoice_pdf, goods_receipt_note_pdf, enable_ocr=False
):
    """Extract three PDFs and reconcile only when all required fields are safe.

    Returns a JSON-ready report. Extraction failures stop the workflow before
    the reconciliation engine is called.
    """
    paths = {
        "purchase_order": purchase_order_pdf,
        "invoice": invoice_pdf,
        "goods_receipt_note": goods_receipt_note_pdf,
    }
    extracted = {}
    errors = {}

    # Try each input so a reviewer can see all extraction problems at once.
    for role, path in paths.items():
        try:
            extracted[role] = extract_pdf_fields(path, role, enable_ocr=enable_ocr)
        except PDFLoadError as error:
            errors[role] = error.to_dict()
        except (OSError, ValueError) as error:
            errors[role] = {
                "code": "PDF_EXTRACTION_ERROR",
                "message": str(error),
            }

    review_reasons = {}
    for role, report in extracted.items():
        if report["status"] != "EXTRACTED":
            review_reasons[role] = report["review_reasons"]

    if errors or review_reasons or len(extracted) != 3:
        return {
            "status": "NEEDS_REVIEW",
            "workflow": "pdf_three_way",
            "reason": "Reconciliation was not run because one or more PDFs could not be extracted safely.",
            "extraction_errors": errors,
            "review_reasons": review_reasons,
            "documents": {
                role: {
                    "status": report["status"],
                    "source": report["source"],
                    "review_reasons": report["review_reasons"],
                }
                for role, report in extracted.items()
            },
            "findings": [],
            "limitations": [
                "No reconciliation is performed unless all three PDFs extract successfully.",
                "Extraction supports only explicitly labelled fields and recognized pipe-table layouts.",
                "PDF text evidence is a page number and text snippet, not a visual coordinate.",
            ],
        }

    documents = {
        role: report["document"] for role, report in extracted.items()
    }
    report = reconcile_three_way(
        documents["purchase_order"],
        documents["invoice"],
        documents["goods_receipt_note"],
    )
    report["workflow"] = "pdf_three_way"
    report["documents"] = {
        role: {
            "status": extracted[role]["status"],
            "source": extracted[role]["source"],
        }
        for role in ROLES
    }

    # Keep the engine's existing JSON Pointer evidence, and enrich it with
    # the original PDF page and snippet when that pointer has a known source.
    evidence_indexes = {
        role: _evidence_index(extracted[role]) for role in ROLES
    }
    for finding in report.get("findings", []):
        evidence = finding.get("evidence", {})
        for side in ("expected", "actual"):
            item = evidence.get(side)
            if not isinstance(item, dict):
                continue
            role = item.get("document_role")
            pointer = item.get("json_pointer")
            pdf_evidence = evidence_indexes.get(role, {}).get(pointer)
            if pdf_evidence:
                item["pdf_evidence"] = pdf_evidence

    report["limitations"] = list(report.get("limitations", [])) + [
        "PDF extraction evidence refers to extracted text snippets, not verified visual coordinates.",
        "Successful extraction and reconciliation do not prove document authenticity or physical delivery.",
    ]
    return report
