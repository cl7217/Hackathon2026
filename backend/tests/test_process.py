import unittest
from unittest.mock import patch

from app.pipeline.extractor import ExtractionCandidate
from app.pipeline.ingest import PageImage
from app.pipeline.process import extract_document


class PipelineTests(unittest.TestCase):
    @patch("app.pipeline.process._EXTRACTOR")
    @patch("app.pipeline.process.read_ocr", side_effect=["כללית", "דנה"])
    @patch("app.pipeline.process.render_document")
    def test_typed_region_uses_local_ocr_and_emits_progress(
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
        self.assertEqual(read_ocr.call_count, 2)

    @patch("app.pipeline.process._EXTRACTOR")
    @patch("app.pipeline.process.read_ocr", return_value="כללית")
    @patch("app.pipeline.process.render_document")
    def test_handwritten_region_is_sent_to_vision_crop(
        self, render_document, _read_ocr, extractor
    ):
        render_document.return_value = [PageImage(1, b"png-page", 20, 20)]
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

        result = extract_document("sample.png", b"image")

        extractor.extract_field_crop.assert_called_once()
        self.assertEqual(result[0].fields["first_name"].source, "vlm")
        self.assertTrue(result[0].fields["first_name"].handwritten)


if __name__ == "__main__":
    unittest.main()
