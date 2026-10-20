import logging
import re
import subprocess

from app.config import (
    FIELD_NAMES,
    OCR_LANGUAGES,
    SENDER_ALLOWLIST,
    TESSERACT_COMMAND,
)
from app.pipeline.extractor import ExtractionCandidate, ExtractorUnavailableError
from app.pipeline.rules import extract_with_rules

logger = logging.getLogger(__name__)


def read_ocr(image: bytes) -> str:
    try:
        result = subprocess.run(
            [
                TESSERACT_COMMAND,
                "stdin",
                "stdout",
                "-l",
                OCR_LANGUAGES,
                "--psm",
                "6",
            ],
            input=image,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as error:
        logger.error("Local Tesseract OCR is unavailable (%s).", type(error).__name__)
        return ""

    if result.returncode != 0:
        logger.error(
            "Tesseract OCR failed. Exit code=%s, stderr=%s",
            result.returncode,
            result.stderr.decode("utf-8", errors="replace")[:2000],
        )
        return ""

    return result.stdout.decode("utf-8", errors="replace").strip()


def _compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def _field(value: str | list[str] | None, raw: str | None = None) -> dict:
    return {
        "value": value,
        "raw": raw if raw is not None else value if isinstance(value, str) else None,
        "bbox": None,
        "handwritten": False,
    }


def _labelled_text(lines: list[str], labels: tuple[str, ...]) -> str | None:
    label_pattern = "|".join(labels)
    stop_pattern = (
        r"שם\s*פרטי|שם\s*משפחה|ת\.?\s*ז\.?|תעודת\s*זהות|"
        r"מספר\s*מרכזי|מרכזי|מספר\s*התחייבות|התחייבות|דרישה|דגימה|"
        r"תאריך|גורם\s*שולח|גורם\s*מפנה|קופת\s*חולים|בית\s*חולים"
    )
    for line in lines:
        match = re.search(rf"(?:{label_pattern})\s*[:：-]?\s*(.+)", line, re.IGNORECASE)
        if not match:
            continue
        value = re.split(
            rf"\s+(?=(?:{stop_pattern})(?:\s|[:：-]|$))",
            match.group(1),
            maxsplit=1,
        )[0]
        value = value.strip(" \t:：-")
        if value and not re.fullmatch(r"[\d\s./-]+", value):
            return value
    return None


def _recognized_sender(text: str) -> str | None:
    compact_text = _compact(text)
    health_funds = ("כללית", "מכבי", "מאוחדת", "לאומית")
    hospitals = [
        name
        for name in SENDER_ALLOWLIST
        if _compact(name) not in {_compact(item) for item in health_funds}
        and _compact(name) != _compact("בית חולים")
    ]
    matches = {
        _compact(name): name
        for name in (*health_funds, *hospitals)
        if _compact(name) in compact_text
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _explicit_health_fund(text: str) -> str | None:
    health_funds = ("כללית", "מכבי", "מאוחדת", "לאומית")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if re.search(r"קופת\s*חולים|קופה|מבוטח\s*ב", line):
            search_text = " ".join(lines[index:index + 2])
            match = next(
                (
                    name
                    for name in health_funds
                    if _compact(name) in _compact(search_text)
                ),
                None,
            )
            if match:
                return match
    return None


def _extract_text_fields(text: str, form_type: str) -> dict[str, dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    fields = extract_with_rules(text, form_type)

    first_name = _labelled_text(lines, (r"שם\s*פרטי",))
    if first_name:
        fields["first_name"] = _field(first_name)

    last_name = _labelled_text(lines, (r"שם\s*משפחה",))
    if last_name:
        fields["last_name"] = _field(last_name)

    sender = _labelled_text(
        lines,
        (
            r"גורם\s*שולח",
            r"גורם\s*מפנה",
            r"מוסד\s*שולח",
            r"מוסד\s*מפנה",
            r"שם\s*המוסד",
        ),
    )
    recognized_sender = _recognized_sender(sender) if sender else None
    if recognized_sender:
        fields["sender"] = _field(recognized_sender, sender or recognized_sender)

    health_fund = _explicit_health_fund(text)
    if health_fund:
        fields["health_fund"] = _field(health_fund)

    if re.search(r"התקבל", text):
        fields["received_stamp"] = _field("התקבל")

    return fields


class OCRRulesExtractor:
    def extract(
        self,
        image: bytes,
        *,
        form_type: str,
        ocr_text: str,
        width: int,
        height: int,
    ) -> ExtractionCandidate:
        fields = _extract_text_fields(ocr_text, form_type)
        for field_name in FIELD_NAMES:
            fields.setdefault(field_name, _field(None))
        return ExtractionCandidate(fields=fields, raw_response="")

    def extract_field_crop(
        self,
        image: bytes,
        *,
        field_name: str,
        bbox: list[int],
        width: int,
        height: int,
    ) -> dict:
        if field_name not in FIELD_NAMES:
            raise ValueError(f"Unsupported extraction field: {field_name}")
        raise ExtractorUnavailableError(
            "OCR-only extraction cannot determine field values from a crop without its label."
        )
