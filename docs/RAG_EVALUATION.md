# RAG Evaluation Baseline

The expanded offline evaluation uses 13 synthetic questions and 10 chunks:
11 answerable and 2 unanswerable.

| Method | Recall@1 | Recall@3 | MRR |
|---|---:|---:|---:|
| BM25 | 0.818 | 0.909 | 0.864 |
| BM25 + lexical rerank | 0.909 | 0.909 | 0.909 |
| BM25 + query expansion | 1.000 | 1.000 | 1.000 |

These are baseline results on a small designed dataset, not production accuracy.
Recall@k measures whether expected evidence appears in the first k results.
MRR rewards ranking expected evidence higher. Unanswerable retrieval rate is
not the same as hallucination rate.

Known gaps: limited manual paraphrases, no semantic entailment verification,
no representative real supplier documents, and no real-LLM answer evaluation.

Next experiment: add reviewed paraphrases, similar distractors, contradictory
evidence, missing-evidence questions, and numeric/identifier cases. Freeze
expected evidence labels before comparing systems. Report per-group counts,
Recall@1/3, MRR, abstention precision/recall, citation correctness, and failures.
