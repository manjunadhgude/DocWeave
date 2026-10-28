import unittest
from docweave.rag.answering import answer_question
from docweave.rag.models import Chunk, RetrievedChunk


class RAGAnswerGroundingTests(unittest.TestCase):
    def setUp(self):
        chunk = Chunk("chunk-1", "doc-1", "Invoice total is 120 dollars.", "invoice.pdf", 3)
        self.retrieved = [RetrievedChunk(chunk, 0.8, "keyword")]

    def test_supported_answer_returns_citation(self):
        class Provider:
            def generate(self, question, evidence):
                return "The invoice total is 120 dollars."
        answer = answer_question("What is the invoice total?", self.retrieved, Provider())
        self.assertFalse(answer.abstained)
        self.assertEqual(answer.citations[0].chunk_id, "chunk-1")
        self.assertEqual(answer.citations[0].page_number, 3)
        self.assertEqual(answer.evidence_chunk_ids, ("chunk-1",))

    def test_unrelated_answer_abstains(self):
        class Provider:
            def generate(self, question, evidence):
                return "Paris is the capital of France."
        answer = answer_question("What is the invoice total?", self.retrieved, Provider())
        self.assertTrue(answer.abstained)
        self.assertEqual(answer.citations, ())
        self.assertEqual(answer.evidence_chunk_ids, ())

    def test_empty_or_non_string_provider_result_abstains(self):
        for result in ("   ", None):
            with self.subTest(result=result):
                class Provider:
                    def generate(self, question, evidence):
                        return result
                self.assertTrue(answer_question("question", self.retrieved, Provider()).abstained)

    def test_score_threshold_excludes_weak_evidence(self):
        class Provider:
            def generate(self, question, evidence):
                self.fail("Provider must not run without qualifying evidence.")
        answer = answer_question("question", self.retrieved, Provider(), min_score=0.8)
        self.assertTrue(answer.abstained)

    def test_provider_abstention_is_preserved(self):
        class Provider:
            def generate(self, question, evidence):
                return "INSUFFICIENT_EVIDENCE"
        self.assertTrue(answer_question("question", self.retrieved, Provider()).abstained)


if __name__ == "__main__":
    unittest.main()
