import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docweave.rag.ingest import load_pages, RAGIngestError


class RAGIngestErrorTests(unittest.TestCase):
    def test_pdf_extractor_error_becomes_rag_ingest_error(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.pdf"
            path.write_bytes(b"%PDF-test")

            with patch(
                "docweave.pdf_ingest.extract_pdf_text",
                side_effect=ValueError("simulated extraction failure"),
            ):
                with self.assertRaisesRegex(
                    RAGIngestError, "PDF extraction failed"
                ):
                    load_pages(path)


if __name__ == "__main__":
    unittest.main()
