import re

from app.config import SENDER_ALLOWLIST
from app.pipeline.normalize import is_valid_israeli_id, normalize_date

COMMITMENT_PREFIXES = {
    "clalit": "30",
    "leumit": "12",
    "meuhedet": "73",
    "maccabi": "26",
}
HEALTH_FUND_NAMES = {
    "כללית": "clalit",
    "מכבי": "maccabi",
    "מאוחדת": "meuhedet",
    "לאומית": "leumit",
}


def commitment_prefix(form_type: str, health_fund: str | None = None) -> str | None:
    prefix = COMMITMENT_PREFIXES.get(form_type.casefold())
    if prefix or not health_fund:
        return prefix
    normalized = _compact(health_fund)
    for name, issuer in HEALTH_FUND_NAMES.items():
        if _compact(name) in normalized:
            return COMMITMENT_PREFIXES[issuer]
    return None


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
    allowed_values = {_compact(allowed) for allowed in SENDER_ALLOWLIST}
    health_funds = {_compact(name) for name in HEALTH_FUND_NAMES}
    hospital_names = allowed_values - health_funds - {_compact("בית חולים")}
    return any(
        allowed in candidate
        or (candidate in allowed and len(candidate) >= 4)
        for allowed in hospital_names
    ) or any(fund in candidate for fund in health_funds) or (
        _compact("בית חולים") in candidate and len(candidate) > len(_compact("בית חולים"))
    )


def health_fund_is_allowed(value: str) -> bool:
    candidate = _compact(value)
    return bool(candidate) and any(
        _compact(name) in candidate for name in HEALTH_FUND_NAMES
    )


def _numeric_identifiers(value: str | list[str]) -> list[str]:
    values = value if isinstance(value, list) else [value]
    normalized = []
    for item in values:
        candidate = str(item).strip()
        if not re.fullmatch(r"\d+(?:[\s./-]\d+)*", candidate):
            return []
        normalized.append(re.sub(r"\D", "", candidate))
    return normalized


def validate_user_value(
    name: str,
    value: str | list[str] | None,
    form_type: str,
    health_fund: str | None = None,
) -> tuple[str, float, dict[str, bool | None]]:
    if value is None or value == "" or value == []:
        return "empty", 0.0, {"found": False}
    candidate = value if isinstance(value, str) else " ".join(value)
    signals = {"found": True, "field_valid": True}
    if name == "id_number":
        signals["field_valid"] = is_valid_israeli_id(candidate)
    elif name == "document_date":
        signals["field_valid"] = normalize_date(candidate)[1]
    elif name in {"first_name", "last_name"}:
        signals["field_valid"] = bool(
            re.fullmatch(r"[A-Za-z\u0590-\u05FF][A-Za-z\u0590-\u05FF '’-]{0,79}", candidate)
        )
    elif name in {"sender", "health_fund"}:
        signals["field_valid"] = (
            health_fund_is_allowed(candidate)
            if name == "health_fund"
            else sender_is_allowed(candidate)
        )
    elif name == "received_stamp":
        signals["field_valid"] = "התקבל" in _compact(candidate)
    elif name == "center_number":
        signals["numeric_format"] = bool(_numeric_identifiers(value))
    elif name == "commitment_number":
        prefix = commitment_prefix(form_type, health_fund)
        identifiers = _numeric_identifiers(value)
        signals["numeric_format"] = bool(identifiers)
        if prefix:
            signals["commitment_prefix_match"] = bool(identifiers) and all(
                item.startswith(prefix) for item in identifiers
            )
    confidence = 1.0 if all(signals.values()) else 0.5
    state = "green" if all(signals.values()) else "orange"
    return state, confidence, signals


def evaluate_field(
    name: str,
    value: str | list[str] | None,
    *,
    page: int,
    bbox: list[int] | None,
    handwritten: bool,
    ocr_text: str,
    classifier_confident: bool,
    form_type: str | None = None,
    health_fund: str | None = None,
    minimum_confidence: float = 0.75,
) -> tuple[str, float, dict[str, bool | None]]:
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
        signals["field_valid"] = health_fund_is_allowed(candidate)
    elif name == "received_stamp":
        signals["field_valid"] = "התקבל" in _compact(candidate)
    elif name == "center_number":
        signals["numeric_format"] = bool(_numeric_identifiers(value))
    elif name == "commitment_number":
        prefix = commitment_prefix(form_type or "", health_fund)
        identifiers = _numeric_identifiers(value)
        signals["numeric_format"] = bool(identifiers)
        if prefix:
            signals["commitment_prefix_match"] = bool(identifiers) and all(
                item.startswith(prefix)
                for item in identifiers
            )

    confidence = round(sum(signals.values()) / len(signals), 2)
    state = (
        "green"
        if all(signals.values()) and confidence >= minimum_confidence and page > 0
        else "orange"
    )
    return state, confidence, signals
