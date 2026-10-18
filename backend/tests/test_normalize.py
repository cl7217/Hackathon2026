import unittest

from app.pipeline.normalize import (
    is_valid_israeli_id,
    normalize_date,
    normalize_id_number,
    normalize_identifier_list,
)


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


if __name__ == "__main__":
    unittest.main()
