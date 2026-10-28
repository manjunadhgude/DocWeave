"""Harder synthetic RAG retrieval challenge. No API key or model required."""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docweave.rag.models import Chunk
from docweave.rag.keyword import bm25_search, bm25_search_expanded
from docweave.rag.reranking import rerank


CHUNKS = [
    Chunk("inv_a", "invoice", "Invoice INV-310 total is 840 USD.", "invoice_a.txt", 1),
    Chunk("inv_b", "invoice", "Invoice INV-311 total is 480 USD.", "invoice_b.txt", 1),
    Chunk("po_a", "purchase_order", "Purchase order PO-700 approved amount is 900 USD.", "po_a.txt", 1),
    Chunk("po_b", "purchase_order", "Purchase order PO-701 approved amount is 840 USD.", "po_b.txt", 1),
    Chunk("grn_a", "receipt", "Goods receipt GRN-90 records 18 units received.", "grn_a.txt", 1),
    Chunk("grn_b", "receipt", "Goods receipt GRN-91 records 12 units received.", "grn_b.txt", 1),
    Chunk("bill_a", "invoice_detail", "Invoice INV-310 bills 20 units; the receipt records 18 units.", "bill_a.txt", 1),
    Chunk("bill_b", "invoice_detail", "Invoice INV-311 bills 12 units; the receipt records 12 units.", "bill_b.txt", 1),
    Chunk("supplier_a", "supplier", "Supplier Acme Components uses supplier ID SUP-42.", "supplier_a.txt", 1),
    Chunk("supplier_b", "supplier", "Supplier Apex Components uses supplier ID SUP-24.", "supplier_b.txt", 1),
    Chunk("due_a", "invoice_detail", "Invoice INV-310 payment due date is 15 December 2026.", "due_a.txt", 1),
    Chunk("due_b", "invoice_detail", "Invoice INV-311 payment due date is 20 December 2026.", "due_b.txt", 1),
    Chunk("refund_a", "policy", "Refunds above 500 USD require manager approval.", "refund_policy.txt", 1),
    Chunk("refund_b", "policy", "Refunds of 500 USD or less can be approved by a support agent.", "refund_policy.txt", 2),
    Chunk("contract_a", "contract", "Contract CT-20 specifies payment terms of net 30 days.", "contract.txt", 1),
    Chunk("contract_b", "contract", "Contract CT-21 specifies payment terms of net 60 days.", "contract.txt", 2),
    Chunk("change_a", "amendment", "Amendment AM-9 changes PO-700 delivery quantity from 18 to 20 units.", "amendment.txt", 1),
    Chunk("bank_a", "supplier", "Supplier bank account information is not included in this record.", "supplier.txt", 2),
]

# expected lists contain all evidence IDs needed for the retrieval question.
# An empty list means the answer is intentionally unavailable.
CASES = [
    {"id": "P01", "group": "paraphrase", "q": "How much money does INV-310 charge?", "expected": ["inv_a"]},
    {"id": "P02", "group": "paraphrase", "q": "When must invoice 310 be paid?", "expected": ["due_a"]},
    {"id": "P03", "group": "paraphrase", "q": "How many items were actually delivered on GRN-90?", "expected": ["grn_a"]},
    {"id": "P04", "group": "paraphrase", "q": "Who needs to authorize a refund for 700 dollars?", "expected": ["refund_a"]},
    {"id": "H01", "group": "hard_negative", "q": "What is the total for invoice INV-310, not INV-311?", "expected": ["inv_a"]},
    {"id": "H02", "group": "hard_negative", "q": "What amount was approved for purchase order PO-700?", "expected": ["po_a"]},
    {"id": "H03", "group": "hard_negative", "q": "What is the due date for INV-311 rather than INV-310?", "expected": ["due_b"]},
    {"id": "H04", "group": "hard_negative", "q": "What is supplier ID SUP-24 for Apex Components?", "expected": ["supplier_b"]},
    {"id": "C01", "group": "contradiction", "q": "For PO-700, what quantity was originally ordered and what quantity did amendment AM-9 set?", "expected": ["po_a", "change_a"]},
    {"id": "C02", "group": "contradiction", "q": "Compare billed and received quantities for INV-310.", "expected": ["bill_a", "grn_a"]},
    {"id": "C03", "group": "contradiction", "q": "What are the payment terms stated in CT-20 and CT-21?", "expected": ["contract_a", "contract_b"]},
    {"id": "C04", "group": "contradiction", "q": "Which refund approval rule applies above and at or below 500 USD?", "expected": ["refund_a", "refund_b"]},
    {"id": "U01", "group": "unanswerable", "q": "What is the bank account number for SUP-42?", "expected": []},
    {"id": "U02", "group": "unanswerable", "q": "What tax registration number belongs to INV-310?", "expected": []},
    {"id": "U03", "group": "unanswerable", "q": "Who signed GRN-90 and at what exact time?", "expected": []},
    {"id": "E01", "group": "exact_value", "q": "Give the exact invoice amount for INV-311 in USD.", "expected": ["inv_b"]},
    {"id": "E02", "group": "exact_value", "q": "How many units were billed on INV-310?", "expected": ["bill_a"]},
    {"id": "E03", "group": "exact_value", "q": "State the payment period for contract CT-21.", "expected": ["contract_b"]},
]


def score(rankings, cases):
    answerable = [(case, ranking) for case, ranking in zip(cases, rankings)
                  if case["expected"]]
    unanswerable = [(case, ranking) for case, ranking in zip(cases, rankings)
                    if not case["expected"]]

    hit1 = hit3 = all3 = 0
    reciprocal_ranks = []
    for case, ranking in answerable:
        ids = [r.chunk.chunk_id for r in ranking]
        expected = case["expected"]
        hit1 += int(bool(ids) and ids[0] in expected)
        hit3 += int(any(item in ids[:3] for item in expected))
        all3 += int(all(item in ids[:3] for item in expected))
        first_rank = min((ids.index(item) + 1 for item in expected if item in ids), default=0)
        reciprocal_ranks.append(1 / first_rank if first_rank else 0.0)

    return {
        "answerable_count": len(answerable),
        "recall_at_1": round(hit1 / max(1, len(answerable)), 4),
        "recall_at_3": round(hit3 / max(1, len(answerable)), 4),
        "all_expected_evidence_at_3": round(all3 / max(1, len(answerable)), 4),
        "mrr": round(sum(reciprocal_ranks) / max(1, len(answerable)), 4),
        "unanswerable_count": len(unanswerable),
        "unanswerable_retrieval_rate": round(
            sum(bool(r) for _, r in unanswerable) / max(1, len(unanswerable)), 4
        ),
    }


def main():
    methods = {
        "bm25": bm25_search,
        "bm25_plus_lexical_rerank": None,
        "bm25_query_expansion": bm25_search_expanded,
    }
    rankings_by_method = defaultdict(list)
    details = []

    for case in CASES:
        base = bm25_search(case["q"], CHUNKS, top_k=6)
        reranked = rerank(case["q"], base, top_k=6)
        expanded = bm25_search_expanded(case["q"], CHUNKS, top_k=6)
        current = {
            "bm25": base,
            "bm25_plus_lexical_rerank": reranked,
            "bm25_query_expansion": expanded,
        }
        for name, ranking in current.items():
            rankings_by_method[name].append(ranking)

        row = {
            "id": case["id"],
            "group": case["group"],
            "question": case["q"],
            "expected_evidence_ids": case["expected"],
            "ranked_ids": {
                name: [r.chunk.chunk_id for r in ranking]
                for name, ranking in current.items()
            },
        }
        for name, ranking in current.items():
            ids = [r.chunk.chunk_id for r in ranking]
            row.setdefault("checks", {})[name] = {
                "any_expected_in_top3": (
                    any(x in ids[:3] for x in case["expected"])
                    if case["expected"] else None
                ),
                "all_expected_in_top3": (
                    all(x in ids[:3] for x in case["expected"])
                    if case["expected"] else None
                ),
                "returned_results_on_unanswerable": (
                    bool(ranking) if not case["expected"] else None
                ),
            }
        details.append(row)

    by_group = {}
    for group in sorted({c["group"] for c in CASES}):
        subset = [c for c in CASES if c["group"] == group]
        indices = [CASES.index(c) for c in subset]
        by_group[group] = {
            name: score([rankings_by_method[name][i] for i in indices], subset)
            for name in rankings_by_method
        }

    report = {
        "dataset": "docweave_rag_challenge_synthetic_v1",
        "chunk_count": len(CHUNKS),
        "case_count": len(CASES),
        "group_counts": {
            group: sum(c["group"] == group for c in CASES)
            for group in sorted({c["group"] for c in CASES})
        },
        "overall_metrics": {
            name: score(rankings, CASES)
            for name, rankings in rankings_by_method.items()
        },
        "metrics_by_group": by_group,
        "cases": details,
        "limitations": [
            "Small synthetic dataset; no real-world accuracy claim.",
            "Expected evidence labels are hand-authored and need independent review.",
            "Retrieval of contradictory evidence does not prove contradiction resolution.",
            "Retrieval metrics do not evaluate generated answer correctness.",
            "Unanswerable retrieval rate measures returned chunks, not hallucination.",
            "No semantic embeddings or real LLM are used by this benchmark.",
        ],
    }

    out = Path(".docweave-rag-reports/rag-challenge-v1.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print(f"\nSaved report: {out}")


if __name__ == "__main__":
    main()
