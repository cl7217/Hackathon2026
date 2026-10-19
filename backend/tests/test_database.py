import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.schemas.extraction import ExtractedField, FormExtraction
from app.services import database


class DatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.paths = (
            patch.object(database, "DATA_DIR", root),
            patch.object(database, "DATABASE_PATH", root / "test.sqlite3"),
        )
        for path_patch in self.paths:
            path_patch.start()
        database.initialize_database()

    def tearDown(self):
        for path_patch in self.paths:
            path_patch.stop()
        self.temp_dir.cleanup()

    def test_records_can_be_searched_filtered_corrected_and_approved(self):
        batch_id = database.create_batch()
        extraction = FormExtraction(
            form_type="clalit",
            page=1,
            fields={
                "first_name": ExtractedField(value="דנה", state="orange"),
                "id_number": ExtractedField(value="123456782", state="green", needs_review=False),
                "sender": ExtractedField(value="כללית", state="green", needs_review=False),
            },
        )
        _, document_id = database.save_extraction("sample.pdf", [extraction], batch_id)

        found = database.list_records(search="דנה", sender="כללית")
        self.assertEqual(found["total"], 1)
        self.assertFalse(found["records"][0]["approved"])

        self.assertTrue(database.correct_field(document_id, "first_name", "דנה", page=1))
        self.assertTrue(database.correct_field(document_id, "id_number", "123456789", page=1))
        approved, reason = database.approve_document(document_id, page=1)
        self.assertFalse(approved)
        self.assertEqual(reason, "review_required")
        self.assertTrue(database.correct_field(document_id, "id_number", "123456782", page=1))
        approved, reason = database.approve_document(document_id, page=1)
        self.assertTrue(approved)
        self.assertIsNone(reason)

        found = database.list_records(approved=True, limit=1)
        self.assertEqual(found["total"], 1)
        self.assertEqual(found["records"][0]["fields"][0]["name"], "first_name")


if __name__ == "__main__":
    unittest.main()
