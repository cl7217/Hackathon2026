import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import audit


class AuditLogTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.log_path = Path(self.temp_dir.name) / "logs" / "events.jsonl"
        self.path_patch = patch.object(audit, "AUDIT_LOG_PATH", self.log_path)
        self.path_patch.start()

    def tearDown(self):
        self.path_patch.stop()
        self.temp_dir.cleanup()

    def test_events_are_persisted_and_filterable_by_trace_batch_and_document(self):
        audit.record_event(
            "upload.received",
            function="upload",
            trace_id="trace-a",
            batch_id="batch-a",
            details={"file_extension": ".pdf", "file_bytes": 42},
        )
        audit.record_event(
            "document.completed",
            function="process",
            trace_id="trace-a",
            batch_id="batch-a",
            document_id="document-a",
            status="success",
        )
        audit.record_event(
            "document.completed",
            function="process",
            trace_id="trace-b",
            batch_id="batch-b",
            status="success",
        )

        events = audit.read_events(batch_id="batch-a", trace_id="trace-a")
        document_events = audit.read_events(document_id="document-a")

        self.assertEqual([event["event"] for event in events], [
            "upload.received",
            "document.completed",
        ])
        self.assertEqual(events[1]["document_id"], "document-a")
        self.assertTrue(all("timestamp" in event and "function" in event for event in events))
        self.assertEqual([event["event"] for event in document_events], ["document.completed"])

    def test_sensitive_detail_keys_are_rejected_before_writing(self):
        with self.assertRaises(ValueError):
            audit.record_event(
                "field.validated",
                function="evaluate_field",
                details={"field": "first_name", "value": "patient name"},
            )

        self.assertFalse(self.log_path.exists())

    def test_rotation_keeps_only_configured_number_of_backups(self):
        with (
            patch.object(audit, "_MAX_LOG_BYTES", 300),
            patch.object(audit, "_BACKUP_COUNT", 2),
        ):
            for index in range(5):
                audit.record_event(
                    "step",
                    function="test",
                    trace_id=f"trace-{index}",
                    details={"step": index},
                )

        self.assertTrue(self.log_path.exists())
        self.assertTrue(self.log_path.with_name("events.jsonl.1").exists())
        self.assertTrue(self.log_path.with_name("events.jsonl.2").exists())
        self.assertFalse(self.log_path.with_name("events.jsonl.3").exists())

        persisted = [
            json.loads(line)
            for path in (
                self.log_path,
                self.log_path.with_name("events.jsonl.1"),
                self.log_path.with_name("events.jsonl.2"),
            )
            for line in path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(len(persisted), 3)


if __name__ == "__main__":
    unittest.main()
