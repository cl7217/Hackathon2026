import unittest

from app.pipeline.normalize import (
    is_valid_israeli_id,
    normalize_date,
    normalize_id_number,
    normalize_identifier_list,
)
from app.pipeline.confidence import evaluate_field, validate_user_value


class NormalizeTests(unittest.TestCase):
    def test_id_number_is_padded_and_checksum_validated(self):
        normalized = normalize_id_number("123-456-782")
        self.assertEqual(normalized, "123456782")
        self.assertTrue(is_valid_israeli_id(normalized))
        self.assertFalse(is_valid_israeli_id("123456789"))

    def test_invalid_id_candidate_is_retained_for_review(self):
        self.assertEqual(normalize_id_number("1234567890"), "1234567890")
        self.assertEqual(normalize_id_number("12345O789"), "12345O789")

    def test_date_formats_are_normalized_and_invalid_dates_rejected(self):
        self.assertEqual(normalize_date("31.12.2020"), ("31/12/2020", True))
        self.assertEqual(normalize_date("31/13/2020")[1], False)

    def test_multiple_identifiers_are_preserved_without_duplicates(self):
        self.assertEqual(
            normalize_identifier_list([" 001 23 ", "00123", "456"]),
            ["00123", "456"],
        )

    def test_commitment_prefixes_match_health_fund_and_form_issuer(self):
        state, _, signals = evaluate_field(
            "commitment_number",
            ["300123", "300456"],
            page=1,
            bbox=[0, 0, 10, 10],
            handwritten=False,
            ocr_text="300123 300456",
            classifier_confident=True,
            form_type="unknown",
            health_fund="כללית",
        )
        self.assertEqual(state, "green")
        self.assertTrue(signals["commitment_prefix_match"])

        state, _, signals = validate_user_value(
            "commitment_number", ["120123"], "clalit", "כללית"
        )
        self.assertEqual(state, "orange")
        self.assertFalse(signals["commitment_prefix_match"])

    def test_corrected_id_requires_a_valid_israeli_checksum(self):
        self.assertEqual(validate_user_value("id_number", "123456782", "clalit")[0], "green")
        self.assertEqual(validate_user_value("id_number", "123456789", "clalit")[0], "orange")

    def test_sender_values_must_match_a_closed_allowlist(self):
        self.assertEqual(validate_user_value("sender", "כללית", "clalit")[0], "green")
        self.assertEqual(validate_user_value("sender", "ביתר עלית-גבע.א", "clalit")[0], "orange")


if __name__ == "__main__":
    unittest.main()
