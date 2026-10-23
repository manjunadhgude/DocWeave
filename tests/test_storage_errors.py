import os
import unittest
from unittest.mock import patch

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///./docweave_test.db",
)

from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from docweave.api import app


class StorageErrorTests(unittest.TestCase):
    def test_history_detail_returns_503_on_database_error(self):
        with TestClient(app) as client:
            with patch.object(
                Session,
                "get",
                side_effect=SQLAlchemyError("simulated database failure"),
            ):
                response = client.get(
                    "/api/v1/reconciliations/nonexistent-record"
                )

        self.assertEqual(response.status_code, 503)
        self.assertIn("temporarily unavailable", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
