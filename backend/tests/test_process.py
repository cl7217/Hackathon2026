from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.config import FIELD_NAMES
from app.pipeline.extractor import ExtractionCandidate
from app.pipeline.ingest import PageImage
from app.pipeline.ocr_extractor import OCRRulesExtractor
from app.pipeline.process import _merge_candidates, extract_document
from app.services import audit


class PipelineTests(unittest.TestCase):
    def test_audit_records_field_presence_without_document_text_or_values(self):
        from app.pipeline import process

        secret_value = "PatientSecret123"
        extractor = MagicMock()
        extractor.extract.return_value = ExtractionCandidate(
            fields={
                "first_name": {
                    "value": secret_value,
                    "raw": secret_value,
                    "handwritten": False,
                }
            },
            raw_response=secret_value,
        )
        page = PageImage(1, b"png-page", 20, 20)

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "audit.jsonl"
            with (
                patch.object(audit, "AUDIT_LOG_PATH", log_path),
                patch.object(process, "render_document", return_value=[page]),
                patch.object(process, "read_ocr", return_value=secret_value),
                patch.object(process, "_get_extractor", return_value=extractor),
            ):
                result = extract_document(
                    "sample.png",
                    b"image",
                    trace_id="trace-private-data",
                )

                audit_content = log_path.read_text(encoding="utf-8")
                events = audit.read_events(trace_id="trace-private-data")

        self.assertEqual(result[0].fields["first_name"].value, secret_value)
        self.assertNotIn(secret_value, audit_content)
        field_event = next(
            event
            for event in events
            if event["event"] == "field.validated"
            and event["details"]["field"] == "first_name"
        )
        self.assertTrue(field_event["details"]["found"])
        self.assertIn("document.processing_completed", [event["event"] for event in events])

    @patch("app.pipeline.process._EXTRACTOR")
    @patch("app.pipeline.process.read_ocr", return_value="כללית דנה")
    @patch("app.pipeline.process.render_document")
    def test_printed_field_uses_page_model_and_emits_progress(
        self, render_document, read_ocr, extractor
    ):
        page = PageImage(1, b"png-page", 20, 20)
        render_document.return_value = [page]
        extractor.extract.return_value = ExtractionCandidate(
            fields={
                "first_name": {
                    "value": "דנה",
                    "raw": "דנה",
                    "bbox": [1, 1, 10, 10],
                    "handwritten": False,
                }
            },
            raw_response="{}",
        )
        extractor.crop_field_image.return_value = b"png-crop"
        stages = []
        rendered = []

        result = extract_document(
            "sample.png",
            b"image",
            on_stage=stages.append,
            on_page_rendered=rendered.append,
        )

        first_name = result[0].fields["first_name"]
        self.assertEqual(first_name.value, "דנה")
        self.assertEqual(first_name.source, "ocr")
        extractor.extract_field_crop.assert_not_called()
        self.assertEqual(rendered, [page])
        self.assertEqual(
            stages,
            ["ingestion", "classification", "extraction"]
            + ["validation"] * 9,
        )
        self.assertEqual(read_ocr.call_count, 1)

    @patch("app.pipeline.process._get_extractor")
    @patch("app.pipeline.process.read_ocr", return_value="כללית")
    @patch("app.pipeline.process.render_document")
    def test_handwritten_region_is_sent_to_vision_crop(
        self, render_document, _read_ocr, get_extractor
    ):
        from app.pipeline import process

        render_document.return_value = [PageImage(1, b"png-page", 20, 20)]
        extractor = MagicMock()
        get_extractor.return_value = extractor
        extractor.extract.return_value = ExtractionCandidate(
            fields={
                "first_name": {
                    "value": "דנה",
                    "raw": "דנה",
                    "bbox": [1, 1, 10, 10],
                    "handwritten": True,
                }
            },
            raw_response="{}",
        )
        extractor.extract_field_crop.return_value = {
            "value": "דנה",
            "raw": "דנה",
            "handwritten": True,
        }

        with patch.object(process, "EXTRACTION_MODE", "gemini"):
            result = extract_document("sample.png", b"image")

        extractor.extract_field_crop.assert_called_once()
        self.assertEqual(result[0].fields["first_name"].source, "vlm")
        self.assertTrue(result[0].fields["first_name"].handwritten)

    @patch("app.pipeline.process._get_extractor")
    @patch("app.pipeline.process.read_ocr", return_value="כללית")
    @patch("app.pipeline.process.render_document")
    def test_handwritten_date_crop_is_normalized_and_keeps_crop_transcription(
        self, render_document, _read_ocr, get_extractor
    ):
        from app.pipeline import process

        render_document.return_value = [PageImage(1, b"png-page", 20, 20)]
        extractor = MagicMock()
        get_extractor.return_value = extractor
        extractor.extract.return_value = ExtractionCandidate(
            fields={
                "document_date": {
                    "value": "01/01/2025",
                    "raw": "01/01/2025",
                    "bbox": [1, 1, 10, 10],
                    "handwritten": True,
                }
            },
            raw_response="{}",
        )
        extractor.extract_field_crop.return_value = {
            "value": "20.10.2026",
            "raw": "20.10.2026",
            "handwritten": True,
        }

        with patch.object(process, "EXTRACTION_MODE", "gemini"):
            result = extract_document("sample.png", b"image")
        received_date = result[0].fields["document_date"]

        self.assertEqual(received_date.value, "20/10/2026")
        self.assertEqual(received_date.raw, "20.10.2026")
        self.assertTrue(received_date.needs_review)

    def test_ocr_rules_extractor_returns_all_nine_canonical_fields(self):
        candidate = OCRRulesExtractor().extract(
            b"",
            form_type="clalit",
            ocr_text="שם פרטי: דנה",
            width=20,
            height=20,
        )
        self.assertEqual(tuple(candidate.fields), FIELD_NAMES)
        self.assertEqual(candidate.fields["first_name"]["value"], "דנה")

    def test_hybrid_merge_uses_local_values_and_flags_disagreements(self):
        local = ExtractionCandidate(
            fields={
                "first_name": {"value": "דנה", "bbox": [1, 1, 5, 5]},
                "center_number": {"value": ["001", "002"], "handwritten": False},
            },
            raw_response="local",
        )
        gemini = ExtractionCandidate(
            fields={
                "first_name": {"value": "דני", "bbox": [2, 2, 6, 6]},
                "center_number": {"value": ["002", "001"], "handwritten": True},
            },
            raw_response="gemini",
        )

        merged = _merge_candidates(local, gemini)

        self.assertEqual(merged.fields["first_name"]["value"], "דנה")
        self.assertFalse(merged.fields["first_name"]["_engine_agreement"])
        self.assertEqual(merged.fields["first_name"]["bbox"], [1, 1, 5, 5])
        self.assertTrue(merged.fields["center_number"]["_engine_agreement"])
        self.assertTrue(merged.fields["center_number"]["handwritten"])

    def test_hybrid_merge_marks_unavailable_engine_as_incomplete(self):
        local = ExtractionCandidate(
            fields={"first_name": {"value": "דנה"}},
            raw_response="local",
        )

        merged = _merge_candidates(local, None)

        self.assertEqual(merged.fields["first_name"]["value"], "דנה")
        self.assertIsNone(merged.fields["first_name"]["_engine_agreement"])
        self.assertTrue(merged.fields["first_name"]["_engine_check_incomplete"])

    @patch("app.pipeline.process.read_ocr", return_value="כללית")
    @patch("app.pipeline.process.render_document")
    def test_hybrid_mode_runs_both_engines_and_marks_conflicting_value_for_review(
        self, render_document, _read_ocr
    ):
        from app.pipeline import process

        render_document.return_value = [PageImage(1, b"png-page", 20, 20)]
        local = MagicMock()
        local.extract.return_value = ExtractionCandidate(
            fields={"first_name": {"value": "דנה", "bbox": [1, 1, 5, 5]}},
            raw_response="local",
        )
        gemini = MagicMock()
        gemini.extract.return_value = ExtractionCandidate(
            fields={"first_name": {"value": "דני", "bbox": [1, 1, 5, 5]}},
            raw_response="gemini",
        )
        providers = {"local_ocr_rules": local, "gemini": gemini}

        with (
            patch.object(process, "EXTRACTION_MODE", "hybrid"),
            patch.object(process, "_get_extractor", side_effect=providers.__getitem__),
        ):
            result = process.extract_document("sample.png", b"image")

        local.extract.assert_called_once()
        gemini.extract.assert_called_once()
        field = result[0].fields["first_name"]
        self.assertEqual(field.value, "דנה")
        self.assertEqual(field.state, "orange")
        self.assertFalse(field.signals["engine_agreement"])

    @patch("app.pipeline.process.read_ocr", return_value="")
    @patch("app.pipeline.process.render_document")
    def test_gemini_mode_continues_when_local_ocr_is_unavailable(
        self, render_document, _read_ocr
    ):
        from app.pipeline import process

        render_document.return_value = [PageImage(1, b"png-page", 20, 20)]
        gemini = MagicMock()
        gemini.extract.return_value = ExtractionCandidate(
            fields={"first_name": {"value": "דנה"}},
            raw_response="gemini",
        )
        with (
            patch.object(process, "EXTRACTION_MODE", "gemini"),
            patch.object(process, "_get_extractor", return_value=gemini),
        ):
            result = process.extract_document("sample.png", b"image")

        gemini.extract.assert_called_once()
        self.assertEqual(result[0].form_type, "unknown")
        self.assertEqual(result[0].fields["first_name"].value, "דנה")
        self.assertEqual(result[0].fields["first_name"].state, "orange")


if __name__ == "__main__":
    unittest.main()
