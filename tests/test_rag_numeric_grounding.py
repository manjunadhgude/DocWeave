import unittest

from docweave.rag.answering import answer_question
from docweave.rag.models import Chunk, RetrievedChunk


class FixedProvider:
    def __init__(self, answer):
        self.answer = answer

    def generate(self, question, evidence):
        return self.answer


class NumericGroundingTests(unittest.TestCase):
    def setUp(self):
        chunk = Chunk(
            "invoice-310",
            "invoice-310",
            "Invoice INV-310 total is 840 USD.",
            "invoice.txt",
            1,
        )
        self.evidence = [RetrievedChunk(chunk, 1.0, "test")]

    def test_supported_invoice_amount_is_allowed(self):
        answer = answer_question(
            "What is the invoice total?",
            self.evidence,
            FixedProvider("Invoice INV-310 total is 840 USD."),
        )
        self.assertFalse(answer.abstained)

    def test_unsupported_amount_is_rejected_despite_word_overlap(self):
        answer = answer_question(
            "What is the invoice total?",
            self.evidence,
            FixedProvider("Invoice INV-310 total is 999 USD."),
        )
        self.assertTrue(answer.abstained)
        self.assertEqual(
            answer.answer,
            "I could not find sufficient evidence in the supplied documents.",
        )


if __name__ == "__main__":
    unittest.main()
