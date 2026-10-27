import unittest

from docweave.rag.models import Chunk
from docweave.rag.keyword import (
    bm25_search,
    bm25_search_expanded,
    expand_query,
)


class QueryExpansionTests(unittest.TestCase):
    def setUp(self):
        self.chunks = [
            Chunk(
                "supplier-mismatch",
                "review",
                "Supplier mismatch requires manual review.",
                "review.txt",
                1,
            ),
            Chunk(
                "delivery",
                "delivery",
                "Shipping address and delivery window.",
                "delivery.txt",
                1,
            ),
        ]

    def test_vendor_paraphrase_finds_supplier_evidence(self):
        original = bm25_search("vendor name does not match", self.chunks)
        expanded = bm25_search_expanded(
            "vendor name does not match", self.chunks
        )
        self.assertEqual(original, [])
        self.assertEqual(expanded[0].chunk.chunk_id, "supplier-mismatch")

    def test_original_terms_are_preserved(self):
        expanded = expand_query("vendor mismatch")
        self.assertIn("vendor", expanded.split())
        self.assertIn("mismatch", expanded.split())
        self.assertIn("supplier", expanded.split())

    def test_top_k_validation_is_preserved(self):
        with self.assertRaises(ValueError):
            bm25_search_expanded("vendor mismatch", self.chunks, top_k=0)


if __name__ == "__main__":
    unittest.main()
