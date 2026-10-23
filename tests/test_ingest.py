import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from docweave.ingest import DocumentLoadError, load_json_document


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def write_bytes(self, name, content):
        path = self.root / name
        path.write_bytes(content)
        return path

    def test_valid_json_returns_source_fingerprint(self):
        raw = b'{"document_id":"PO-1","lines":[]}'
        path = self.write_bytes("po.json", raw)
        document, source = load_json_document(path, "purchase_order")
        self.assertEqual(document["document_id"], "PO-1")
        self.assertEqual(source["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(source["byte_size"], len(raw))
        self.assertEqual(source["file_name"], "po.json")

    def test_invalid_json_reports_line_and_column(self):
        path = self.write_bytes("bad.json", b'{\n "x": }\n')
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(path, "invoice")
        self.assertEqual(caught.exception.code, "INVALID_JSON")
        self.assertGreaterEqual(caught.exception.details["line"], 1)
        self.assertGreaterEqual(caught.exception.details["column"], 1)

    def test_missing_file_has_structured_error(self):
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(self.root / "missing.json", "invoice")
        self.assertEqual(caught.exception.code, "FILE_READ_ERROR")

    def test_non_object_root_is_rejected(self):
        path = self.write_bytes("array.json", b'[1, 2]')
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(path, "invoice")
        self.assertEqual(caught.exception.code, "INVALID_ROOT_TYPE")

    def test_duplicate_json_keys_are_rejected(self):
        path = self.write_bytes("duplicate.json", b'{"total":"10","total":"20"}')
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(path, "invoice")
        self.assertEqual(caught.exception.code, "DUPLICATE_JSON_KEY")
        self.assertEqual(caught.exception.details["key"], "total")

    def test_nonstandard_nan_is_rejected(self):
        path = self.write_bytes("nan.json", b'{"amount":NaN}')
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(path, "invoice")
        self.assertEqual(caught.exception.code, "NON_STANDARD_NUMBER")

    def test_invalid_utf8_is_rejected(self):
        path = self.write_bytes("encoding.json", b'{"x":"\xff"}')
        with self.assertRaises(DocumentLoadError) as caught:
            load_json_document(path, "invoice")
        self.assertEqual(caught.exception.code, "INVALID_ENCODING")

    def test_utf8_bom_and_unicode_are_supported(self):
        raw = b'\xef\xbb\xbf{"supplier":"\xe2\x9c\x93"}'
        path = self.write_bytes("unicode.json", raw)
        document, _ = load_json_document(path, "invoice")
        self.assertEqual(document["supplier"], "\u2713")


if __name__ == "__main__":
    unittest.main()
