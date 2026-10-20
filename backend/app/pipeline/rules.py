import re

from app.pipeline.normalize import (
    normalize_date,
    normalize_identifier_list,
)

_ID_LABEL = re.compile(r"(?:תעודת\s*זהות|מספר\s*זהות|ת\.?\s*ז\.?)", re.IGNORECASE)
_CENTER_LABEL = re.compile(r"(?:מספר\s*)?מרכזי", re.IGNORECASE)
_COMMITMENT_LABEL = re.compile(
    r"(?:מספר\s*)?(?:התחייבות|דרישה)", re.IGNORECASE
)
_LEUMIT_SAMPLE_LABEL = re.compile(r"דגימה", re.IGNORECASE)
_NUMBER = re.compile(r"(?<!\d)\d+(?:[./-]\d+)*(?!\d)")
_ID_NUMBER = re.compile(r"(?<!\d)\d(?:[\d -]{6,}\d)(?!\d)")
_DATE = re.compile(r"(?<!\d)\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}(?!\d)")
_DATE_LABEL = re.compile(
    r"תאריך\s*(?:קבלה|קבלת\s*הדגימה)", re.IGNORECASE
)
_COMMON_FIELD_BOUNDARY = (
    r"שם\s*פרטי|שם\s*משפחה|תעודת\s*זהות|מספר\s*זהות|ת\.?\s*ז\.?|"
    r"תאריך|התקבל|גורם\s*(?:שולח|מפנה)|מוסד\s*(?:שולח|מפנה)|"
    r"קופת\s*חולים|בית\s*חולים|מספר\s*בדיקה"
)
_FIELD_BOUNDARY = re.compile(
    rf"(?:{_COMMON_FIELD_BOUNDARY}|(?:מספר\s*)?מרכזי|"
    r"(?:מספר\s*)?(?:התחייבות|דרישה)|דגימה)",
    re.IGNORECASE,
)
_CENTER_VALUE_BOUNDARY = re.compile(
    rf"(?:{_COMMON_FIELD_BOUNDARY}|(?:מספר\s*)?(?:התחייבות|דרישה)|דגימה)",
    re.IGNORECASE,
)
_COMMITMENT_VALUE_BOUNDARY = re.compile(
    rf"(?:{_COMMON_FIELD_BOUNDARY}|(?:מספר\s*)?מרכזי)",
    re.IGNORECASE,
)


def _field(value: str | list[str], raw: str) -> dict:
    return {
        "value": value,
        "raw": raw,
        "bbox": None,
        "handwritten": False,
    }


def _numbers_after_label(
    line: str,
    label: re.Pattern[str],
    boundary: re.Pattern[str],
) -> list[str]:
    matches = list(label.finditer(line))
    numbers = []
    for match in matches:
        value_text = line[match.end():]
        next_label = boundary.search(value_text)
        if next_label:
            value_text = value_text[:next_label.start()]
        numbers.extend(
            candidate
            for candidate in _NUMBER.findall(value_text)
            if not _DATE.fullmatch(candidate)
        )
    return normalize_identifier_list(numbers)


def extract_with_rules(ocr_text: str, form_type: str) -> dict[str, dict]:
    """Extract only values anchored to a matching OCR label on the same line."""
    fields: dict[str, dict] = {}
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    center_numbers: list[str] = []

    for index, line in enumerate(lines):
        if "id_number" not in fields:
            match = _ID_LABEL.search(line)
            if match:
                value_text = line[match.end():]
                next_label = _FIELD_BOUNDARY.search(value_text)
                if next_label:
                    value_text = value_text[:next_label.start()]
                candidates = _ID_NUMBER.findall(value_text)
                for candidate in candidates:
                    normalized = re.sub(r"\D", "", candidate)
                    normalized = normalized.zfill(9) if len(normalized) <= 9 else normalized
                    fields["id_number"] = _field(normalized, candidate)
                    break

        center_numbers.extend(
            _numbers_after_label(line, _CENTER_LABEL, _CENTER_VALUE_BOUNDARY)
        )

        commitment_label = _COMMITMENT_LABEL
        if form_type.casefold() == "leumit" and _LEUMIT_SAMPLE_LABEL.search(line):
            commitment_label = _LEUMIT_SAMPLE_LABEL
        commitment_numbers = _numbers_after_label(
            line,
            commitment_label,
            _COMMITMENT_VALUE_BOUNDARY,
        )
        if commitment_numbers:
            previous = fields.get("commitment_number", {}).get("value", [])
            existing = previous if isinstance(previous, list) else [previous]
            combined = normalize_identifier_list(existing + commitment_numbers)
            fields["commitment_number"] = _field(combined, ", ".join(combined))

        received_match = re.search(r"התקבל", line)
        if "document_date" not in fields and received_match:
            for candidate in _DATE.findall(line[received_match.end():]):
                normalized, valid = normalize_date(candidate)
                if valid and normalized:
                    fields["document_date"] = _field(normalized, candidate)
                    break
        if "document_date" not in fields and _CENTER_LABEL.search(line):
            adjacent_lines = lines[index + 1:index + 2]
            for adjacent_line in adjacent_lines:
                if re.search(r"התקבל|תאריך|התחייבות|דרישה|דגימה", adjacent_line):
                    continue
                dates = _DATE.findall(adjacent_line)
                for candidate in dates:
                    normalized, valid = normalize_date(candidate)
                    if valid and normalized:
                        fields["document_date"] = _field(normalized, candidate)
                        break
                if "document_date" in fields:
                    break
        if "document_date" not in fields:
            date_label = _DATE_LABEL.search(line)
            if date_label:
                candidates = _DATE.findall(line[date_label.end():])
                for candidate in candidates:
                    normalized, valid = normalize_date(candidate)
                    if valid and normalized:
                        fields["document_date"] = _field(normalized, candidate)
                        break

    center_numbers = normalize_identifier_list(center_numbers)
    if center_numbers:
        fields["center_number"] = _field(center_numbers, ", ".join(center_numbers))

    return fields
