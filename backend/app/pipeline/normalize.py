import re
from datetime import date, datetime


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split()).strip(" \t\r\n:：-")
    return cleaned or None


def normalize_id_number(value: str | None) -> str | None:
    if value is None:
        return None
    candidate = re.sub(r"[\s-]", "", value)
    if not re.fullmatch(r"\d+", candidate):
        return normalize_text(value)
    return candidate.zfill(9) if len(candidate) <= 9 else candidate


def is_valid_israeli_id(value: str | None) -> bool:
    if value is None or not re.fullmatch(r"\d{9}", value):
        return False
    checksum = 0
    for index, digit in enumerate(map(int, value)):
        product = digit * (1 if index % 2 == 0 else 2)
        checksum += product // 10 + product % 10
    return checksum % 10 == 0


def normalize_date(value: str | None) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    candidate = value.strip()
    for pattern in ("%d/%m/%Y", "%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(candidate, pattern).date()
            if parsed > date.today() or parsed.year < 1900:
                return parsed.strftime("%d/%m/%Y"), False
            return parsed.strftime("%d/%m/%Y"), True
        except ValueError:
            continue
    return normalize_text(candidate), False


def normalize_identifier_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    values = value if isinstance(value, list) else re.split(r"[,;\n]+", value)
    result = []
    for item in values:
        cleaned = re.sub(r"\s+", "", str(item)).strip(".,;:")
        if cleaned and cleaned not in result:
            result.append(cleaned)
    return result
