import re
from difflib import SequenceMatcher

from app.config import SENDER_ALLOWLIST
from app.pipeline.normalize import is_valid_israeli_id, normalize_date


def _compact(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold(), flags=re.UNICODE)


def ocr_agrees(value: str | list[str], ocr_text: str) -> bool:
    values = value if isinstance(value, list) else [value]
    text = _compact(ocr_text)
    return bool(values) and all(_compact(item) in text for item in values if _compact(item))


def sender_is_allowed(value: str) -> bool:
    candidate = _compact(value)
    if not candidate:
        return False
    best_match = max(
        SequenceMatcher(None, candidate, _compact(allowed)).ratio()
        for allowed in SENDER_ALLOWLIST
    )
    return best_match >= 0.88


def evaluate_field(
    name: str,
    value: str | list[str] | None,
    *,
    page: int,
    bbox: list[int] | None,
    handwritten: bool,
    ocr_text: str,
    classifier_confident: bool,
) -> tuple[str, float, dict[str, bool]]:
    if value is None or value == "":
        return "empty", 0.0, {"found": False}

    signals = {
        "found": True,
        "has_location": bool(bbox and len(bbox) == 4 and bbox[2] > bbox[0] and bbox[3] > bbox[1]),
        "ocr_agreement": ocr_agrees(value, ocr_text),
        "not_handwritten": not handwritten,
        "form_type_confident": classifier_confident,
        "field_valid": True,
    }
    candidate = value if isinstance(value, str) else " ".join(value)
    if name == "id_number":
        signals["field_valid"] = is_valid_israeli_id(candidate)
    elif name == "document_date":
        signals["field_valid"] = normalize_date(candidate)[1]
    elif name == "sender":
        signals["field_valid"] = sender_is_allowed(candidate)
    elif name in {"first_name", "last_name"}:
        signals["field_valid"] = bool(
            re.fullmatch(r"[A-Za-z\u0590-\u05FF][A-Za-z\u0590-\u05FF '’-]{0,79}", candidate)
        )
    elif name == "health_fund":
        signals["field_valid"] = sender_is_allowed(candidate)
    elif name in {"center_number", "commitment_number"}:
        # No authoritative number patterns have been supplied yet; do not mark these green.
        signals["field_valid"] = False

    confidence = round(sum(signals.values()) / len(signals), 2)
    state = "green" if all(signals.values()) and page > 0 else "orange"
    return state, confidence, signals
