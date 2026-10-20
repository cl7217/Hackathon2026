import unittest

from app.pipeline.ocr_extractor import OCRRulesExtractor
from app.pipeline.rules import extract_with_rules


class RuleExtractionTests(unittest.TestCase):
    def test_rules_extract_only_labelled_values_and_all_number_lists(self):
        fields = extract_with_rules(
            "\n".join(
                (
                    "תאריך הנפקה 01/02/2025",
                    "ת.ז. 123456782",
                    "מספר מרכזי: 00123 00456",
                    "מרכזי 00789",
                    "מספר התחייבות: 300123",
                    "דרישה 120456",
                    "התקבל 20/10/2026",
                )
            ),
            "clalit",
        )

        self.assertEqual(fields["id_number"]["value"], "123456782")
        self.assertEqual(fields["center_number"]["value"], ["00123", "00456", "00789"])
        self.assertEqual(
            fields["commitment_number"]["value"],
            ["300123", "120456"],
        )
        self.assertEqual(fields["document_date"]["value"], "20/10/2026")

    def test_leumit_dgima_label_is_used_as_commitment_alias(self):
        fields = extract_with_rules("דגימה: 120456", "leumit")
        self.assertEqual(fields["commitment_number"]["value"], ["120456"])

    def test_date_below_center_label_is_extracted(self):
        fields = extract_with_rules("מרכזי: 00123\n20/10/2026", "clalit")
        self.assertEqual(fields["document_date"]["value"], "20/10/2026")

    def test_date_near_but_not_below_center_label_is_not_guessed(self):
        fields = extract_with_rules(
            "מרכזי: 00123\nפרטי מטופל\n20/10/2026",
            "clalit",
        )
        self.assertNotIn("document_date", fields)

    def test_generic_document_date_label_is_not_assumed_to_be_receipt_date(self):
        fields = extract_with_rules("תאריך הנפקה 20/10/2026", "clalit")
        self.assertNotIn("document_date", fields)

    def test_unlabelled_dates_and_numbers_are_not_guessed(self):
        fields = extract_with_rules(
            "12/03/2026\n123456782\n301234",
            "clalit",
        )
        self.assertNotIn("document_date", fields)
        self.assertNotIn("id_number", fields)
        self.assertNotIn("commitment_number", fields)

    def test_invalid_labelled_id_is_retained_for_manual_review(self):
        fields = extract_with_rules("ת.ז. 123456789", "clalit")
        self.assertEqual(fields["id_number"]["value"], "123456789")

    def test_numbers_are_not_taken_from_following_fields_or_dates(self):
        fields = extract_with_rules(
            "ת.ז. 123456789 מספר מרכזי 00123 "
            "תאריך קבלת הדגימה 20/10/2026 "
            "מספר התחייבות 300123 דרישה 300456",
            "clalit",
        )
        self.assertEqual(fields["center_number"]["value"], ["00123"])
        self.assertEqual(
            fields["commitment_number"]["value"],
            ["300123", "300456"],
        )
        self.assertEqual(fields["document_date"]["value"], "20/10/2026")

    def test_commitments_are_not_confused_with_test_numbers(self):
        fields = extract_with_rules(
            "מספר התחייבות 300123 מספר בדיקה 987654 דרישה 300456",
            "clalit",
        )

        self.assertEqual(fields["commitment_number"]["value"], ["300123", "300456"])


class OCRFieldExtractionTests(unittest.TestCase):
    def test_sender_requires_an_explicit_sender_label(self):
        candidate = OCRRulesExtractor().extract(
            b"",
            form_type="clalit",
            ocr_text="כללית\nשם פרטי: דנה",
            width=20,
            height=20,
        )
        self.assertIsNone(candidate.fields["sender"]["value"])

    def test_sender_is_normalized_from_its_label(self):
        candidate = OCRRulesExtractor().extract(
            b"",
            form_type="unknown",
            ocr_text="גורם שולח: בית חולים שיבא",
            width=20,
            height=20,
        )
        self.assertEqual(candidate.fields["sender"]["value"], "שיבא")


if __name__ == "__main__":
    unittest.main()
