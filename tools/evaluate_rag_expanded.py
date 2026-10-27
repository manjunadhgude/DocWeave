"""Expanded synthetic retrieval benchmark; no API key or model required."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docweave.rag.models import Chunk
from docweave.rag.keyword import bm25_search, bm25_search_expanded
from docweave.rag.reranking import rerank


CHUNKS = [
    Chunk("c1", "invoice", "Invoice total amount is 120 USD.", "invoice.txt", 1),
    Chunk("c2", "receipt", "Goods receipt received quantity is 8 units.", "receipt.txt", 1),
    Chunk("c3", "review", "Supplier mismatch requires manual review.", "review.txt", 1),
    Chunk("c4", "delivery", "Shipping address and delivery window.", "delivery.txt", 1),
    Chunk("c5", "purchase_order", "Purchase order PO-481 approved amount is 125 USD.", "po.txt", 1),
    Chunk("c6", "invoice_details", "Invoice supplier is Acme Components. Invoice INV-204 due date is 30 November 2026.", "invoice_details.txt", 1),
    Chunk("c7", "discrepancy", "Goods received quantity is 8 units, but the invoice billed 10 units. Discrepancy is 2 units.", "discrepancy.txt", 2),
    Chunk("c8", "refund_policy", "Refund requests above 500 USD require manager approval.", "refund_policy.txt", 1),
    Chunk("c9", "contract", "Payment terms are net 30 days.", "contract.txt", 1),
    Chunk("c10", "invoice_history", "Invoice INV-205 was superseded by corrected invoice INV-206 on 24 October 2026.", "invoice_history.txt", 2),
]

CASES = [
    {"question": "invoice total", "expected": "c1"},
    {"question": "what amount is on invoice", "expected": "c1"},
    {"question": "how many units arrived", "expected": "c2"},
    {"question": "vendor name does not match", "expected": "c3"},
    {"question": "where is the delivery address", "expected": "c4"},
    {"question": "approved PO-481 amount", "expected": "c5"},
    {"question": "when is INV-204 due", "expected": "c6"},
    {"question": "billed quantity exceeds received quantity", "expected": "c7"},
    {"question": "who approves refunds over 500 dollars", "expected": "c8"},
    {"question": "what are the payment terms", "expected": "c9"},
    {"question": "which invoice replaced INV-205", "expected": "c10"},
    {"question": "supplier bank account number", "expected": None},
    {"question": "quantum tax deduction eligibility", "expected": None},
]


def measure(rankings, cases):
    answerable = [
        (case["expected"], ranking)
        for case, ranking in zip(cases, rankings)
        if case["expected"] is not None
    ]
    n = len(answerable)
    reciprocal_ranks = []
    hits_at_1 = 0
    hits_at_3 = 0

    for gold, ranking in answerable:
        ids = [item.chunk.chunk_id for item in ranking]
        hits_at_1 += int(bool(ids) and ids[0] == gold)
        hits_at_3 += int(gold in ids[:3])
        reciprocal_ranks.append(
            1 / (ids.index(gold) + 1) if gold in ids else 0.0
        )

    unanswerable = [
        ranking
        for case, ranking in zip(cases, rankings)
        if case["expected"] is None
    ]
    false_retrievals = sum(bool(ranking) for ranking in unanswerable)

    return {
        "answerable_cases": n,
        "recall_at_1": hits_at_1 / max(n, 1),
        "recall_at_3": hits_at_3 / max(n, 1),
        "mrr": sum(reciprocal_ranks) / max(n, 1),
        "unanswerable_cases": len(unanswerable),
        "unanswerable_retrieval_rate": (
            false_retrievals / max(len(unanswerable), 1)
        ),
    }


def main():
    methods = {"bm25": [], "bm25_plus_lexical_rerank": [], "bm25_query_expansion": []}
    details = []

    for case in CASES:
        base = bm25_search(case["question"], CHUNKS, top_k=5)
        reranked = rerank(case["question"], base, top_k=5)
        expanded = bm25_search_expanded(case["question"], CHUNKS, top_k=5)
        methods["bm25"].append(base)
        methods["bm25_plus_lexical_rerank"].append(reranked)
        methods["bm25_query_expansion"].append(expanded)

        details.append({
            "question": case["question"],
            "expected_chunk_id": case["expected"],
            "bm25_ranked_ids": [r.chunk.chunk_id for r in base],
            "reranked_ids": [r.chunk.chunk_id for r in reranked],
            "query_expansion_ranked_ids": [r.chunk.chunk_id for r in expanded],
            "bm25_hit_at_3": (
                case["expected"] in [r.chunk.chunk_id for r in base[:3]]
                if case["expected"] else None
            ),
            "reranked_hit_at_3": (
                case["expected"] in [r.chunk.chunk_id for r in reranked[:3]]
                if case["expected"] else None
            ),
            "query_expansion_hit_at_3": (
                case["expected"] in [r.chunk.chunk_id for r in expanded[:3]]
                if case["expected"] else None
            ),
            "unanswerable_query_returned_results": (
                bool(base) if case["expected"] is None else None
            ),
        })

    report = {
        "dataset": "expanded_synthetic",
        "case_count": len(CASES),
        "chunk_count": len(CHUNKS),
        "metrics": {
            name: measure(rankings, CASES)
            for name, rankings in methods.items()
        },
        "cases": details,
        "limitations": [
            "Synthetic dataset; results do not establish real-world accuracy.",
            "Paraphrases are manually written and do not represent broad language variation.",
            "Unanswerable retrieval rate measures returned results, not whether an answer was generated.",
            "Lexical reranking only reorders BM25 candidates and cannot recover missing candidates.",
            "Semantic retrieval and real-LLM answer correctness are not measured.",
        ],
    }

    output = Path(".docweave-rag-reports/rag-evaluation-expanded.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"\nReport saved to: {output}")


if __name__ == "__main__":
    main()
