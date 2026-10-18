from enum import Enum


class FormType(str, Enum):
    CLALIT = "clalit"
    MACCABI = "maccabi"
    MEUHEDET = "meuhedet"
    LEUMIT = "leumit"
    HOSPITAL = "hospital"
    UNKNOWN = "unknown"


_LABELS = {
    FormType.CLALIT: ("כללית", "clalit"),
    FormType.MACCABI: ("מכבי", "maccabi"),
    FormType.MEUHEDET: ("מאוחדת", "meuhedet"),
    FormType.LEUMIT: ("לאומית", "leumit"),
}


def classify_form(ocr_text: str) -> tuple[FormType, bool]:
    normalized = ocr_text.casefold()
    for form_type, labels in _LABELS.items():
        if any(label in normalized for label in labels):
            return form_type, True
    if any(word in normalized for word in ("בית חולים", "מרכז רפואי", "hospital")):
        return FormType.HOSPITAL, True
    return FormType.UNKNOWN, False
