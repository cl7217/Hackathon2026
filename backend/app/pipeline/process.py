from app.pipeline.classify import classify_form
from app.pipeline.confidence import evaluate_field
from app.pipeline.ingest import render_document
from app.config import FIELD_NAMES
from app.pipeline.local_extractor import LocalExtractor, read_ocr
from app.pipeline.normalize import (
    normalize_date,
    normalize_id_number,
    normalize_identifier_list,
    normalize_text,
)
from app.schemas.extraction import ExtractedField, FormExtraction

_EXTRACTOR = LocalExtractor()


def _normalize_candidate(name: str, field: dict) -> tuple[str | list[str] | None, bool]:
    raw_value = field.get("value")
    if isinstance(raw_value, list):
        candidates = [str(item) for item in raw_value if item is not None]
    elif raw_value is None:
        candidates = []
    else:
        candidates = [str(raw_value)]
    handwritten = field.get("handwritten") is True

    if name in {"center_number", "commitment_number"}:
        values = normalize_identifier_list(candidates)
        return values or None, handwritten
    if name == "id_number":
        return normalize_id_number(candidates[0]) if candidates else None, handwritten
    if name == "document_date":
        normalized, _ = normalize_date(candidates[0] if candidates else None)
        return normalized, handwritten
    if name in {"first_name", "last_name", "sender", "health_fund", "received_stamp"}:
        return normalize_text(candidates[0]) if candidates else None, handwritten
    return None, handwritten


def extract_document(filename: str, content: bytes) -> list[FormExtraction]:
    pages = render_document(filename, content)
    extractions = []
    for page in pages:
        ocr_text = read_ocr(page.png)
        form_type, classifier_confident = classify_form(ocr_text)
        candidate = _EXTRACTOR.extract(
            page.png,
            form_type=form_type.value,
            ocr_text=ocr_text,
            width=page.width,
            height=page.height,
        )
        fields = {}
        for name in FIELD_NAMES:
            item = candidate.fields.get(name)
            item = item if isinstance(item, dict) else {}
            value, handwritten = _normalize_candidate(name, item)
            raw = item.get("raw")
            if not isinstance(raw, str):
                raw = None
            bbox = item.get("bbox")
            if (
                not isinstance(bbox, list)
                or len(bbox) != 4
                or any(not isinstance(coordinate, int) for coordinate in bbox)
                or bbox[0] < 0
                or bbox[1] < 0
                or bbox[2] > page.width
                or bbox[3] > page.height
            ):
                bbox = None
            state, confidence, signals = evaluate_field(
                name,
                value,
                page=page.number,
                bbox=bbox,
                handwritten=handwritten,
                ocr_text=ocr_text,
                classifier_confident=classifier_confident,
            )
            fields[name] = ExtractedField(
                value=value,
                page=page.number,
                bbox=bbox,
                raw=raw,
                confidence=confidence,
                state=state,
                needs_review=state != "green",
                signals=signals,
                handwritten=handwritten,
            )
        extractions.append(
            FormExtraction(form_type=form_type.value, page=page.number, fields=fields)
        )
    return extractions
