import unittest
from unittest.mock import patch

from app.schemas.extraction import ExtractedField, FormExtraction
from app.services import supabase_store


class SupabaseStoreTests(unittest.TestCase):
    @patch("app.services.supabase_store._rows")
    def test_record_search_maps_individual_supabase_fields(self, rows):
        rows.side_effect = [
            [
                {
                    "id": "document-id",
                    "batch_id": "batch-id",
                    "filename": "sample.pdf",
                    "status": "complete",
                    "approved": False,
                    "created_at": "2026-10-18T12:00:00+00:00",
                }
            ],
            [
                {
                    "id": "form-id",
                    "document_id": "document-id",
                    "form_type": "leumit",
                    "page": 1,
                    "approved": False,
                }
            ],
            [
                {
                    "form_id": "form-id",
                    "name": "sender",
                    "value_json": "לאומית",
                    "raw": "לאומית",
                    "page": 1,
                    "bbox_json": [1, 2, 3, 4],
                    "source": "vlm",
                    "confidence": 0.5,
                    "state": "orange",
                    "signals_json": {"found": True},
                    "handwritten": False,
                    "corrected_by_user": False,
                }
            ],
        ]

        result = supabase_store.list_records(search="לאומית", approved=False)

        self.assertEqual(result["total"], 1)
        record = result["records"][0]
        self.assertEqual(record["fields"][0]["name"], "sender")
        self.assertEqual(record["fields"][0]["value"], "לאומית")
        self.assertTrue(record["fields"][0]["needs_review"])

    @patch("app.services.supabase_store._request")
    def test_save_extraction_uses_atomic_rpc_with_field_metadata(self, request):
        request.return_value = {"saved": True}
        extraction = FormExtraction(
            form_type="leumit",
            page=2,
            fields={
                "commitment_number": ExtractedField(
                    value=["123", "456"], state="orange", handwritten=True
                )
            },
        )

        batch_id, document_id = supabase_store.save_extraction(
            "sample.pdf", [extraction], batch_id="batch-id"
        )

        self.assertEqual(batch_id, "batch-id")
        self.assertTrue(document_id)
        request.assert_called_once()
        args, kwargs = request.call_args
        self.assertEqual(args, ("POST", "rpc/save_extraction"))
        self.assertEqual(kwargs["payload"]["p_batch_id"], "batch-id")
        form = kwargs["payload"]["p_forms"][0]
        self.assertEqual(form["page"], 2)
        self.assertEqual(form["fields"]["commitment_number"]["value"], ["123", "456"])
        self.assertTrue(form["fields"]["commitment_number"]["handwritten"])


if __name__ == "__main__":
    unittest.main()
