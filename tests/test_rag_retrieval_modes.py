import unittest

from docweave.rag.models import Chunk
from docweave.rag.retrieval import retrieve, hybrid_search


class RetrievalModeTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            Chunk("c3", "review", "Supplier mismatch requires manual review.",
                  "review.txt", 1),
            Chunk("c1", "invoice", "Invoice total amount is 120 USD.",
                  "invoice.txt", 1),
        ]

    def test_expanded_keyword_finds_vendor_supplier_paraphrase(self):
        results = retrieve(
            "vendor name does not match", self.chunks,
            mode="keyword_expanded", top_k=3,
        )
        self.assertTrue(results)
        self.assertEqual(results[0].chunk.chunk_id, "c3")

    def test_original_keyword_mode_remains_available(self):
        results = retrieve(
            "invoice total", self.chunks, mode="keyword", top_k=2
        )
        self.assertEqual(results[0].chunk.chunk_id, "c1")

    def test_expanded_hybrid_lexical_fallback(self):
        results = hybrid_search(
            "vendor name does not match", self.chunks,
            semantic_results=(), top_k=3, query_expansion=True,
        )
        self.assertTrue(results)
        self.assertEqual(results[0].chunk.chunk_id, "c3")

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            retrieve("invoice", self.chunks, mode="unknown")

if __name__ == "__main__":
    unittest.main()
