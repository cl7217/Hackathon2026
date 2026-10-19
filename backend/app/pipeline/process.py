from collections.abc import Callable

from app.pipeline.classify import classify_form
from app.pipeline.confidence import evaluate_field, ocr_agrees
from app.pipeline.ingest import PageImage, render_document
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


def extract_document(
    filename: str,
    content: bytes,
    on_stage: Callable[[str], None] | None = None,
    on_page_rendered: Callable[[PageImage], None] | None = None,
) -> list[FormExtraction]:
    if on_stage:
        on_stage("ingestion")
    pages = render_document(filename, content)
    if on_page_rendered:
        for page in pages:
            on_page_rendered(page)
    extractions = []
    for page in pages:
        if on_stage:
            on_stage("classification")
        ocr_text = read_ocr(page.png)
        form_type, classifier_confident = classify_form(ocr_text)
        if on_stage:
            on_stage("extraction")
        candidate = _EXTRACTOR.extract(
            page.png,
            form_type=form_type.value,
            ocr_text=ocr_text,
            width=page.width,
            height=page.height,
        )
        health_fund, _ = _normalize_candidate(
            "health_fund",
            candidate.fields.get("health_fund")
            if isinstance(candidate.fields.get("health_fund"), dict)
            else {},
        )
        if isinstance(health_fund, list):
            health_fund = health_fund[0] if health_fund else None
        fields = {}
        for name in FIELD_NAMES:
            item = candidate.fields.get(name)
            item = item if isinstance(item, dict) else {}
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
            candidate_value = item.get("value")
            value_items = (
                candidate_value
                if isinstance(candidate_value, list)
                else [candidate_value]
            )
            crop_ocr_text = ""
            if bbox and item.get("handwritten") is not True:
                crop_png = _EXTRACTOR.crop_field_image(
                    page.png,
                    bbox=bbox,
                    width=page.width,
                    height=page.height,
                )
                crop_ocr_text = read_ocr(crop_png)
            needs_crop = bool(
                bbox
                and (
                    item.get("handwritten") is True
                    or candidate_value in (None, "", [])
                    or not ocr_agrees(
                        [str(value) for value in value_items if value is not None],
                        crop_ocr_text or ocr_text,
                    )
                )
            )
            if needs_crop:
                item = _EXTRACTOR.extract_field_crop(
                    page.png,
                    field_name=name,
                    bbox=bbox,
                    width=page.width,
                    height=page.height,
                )
            value, handwritten = _normalize_candidate(name, item)
            raw = item.get("raw")
            if not isinstance(raw, str):
                raw = None
            if on_stage:
                on_stage("validation")
            state, confidence, signals = evaluate_field(
                name,
                value,
                page=page.number,
                bbox=bbox,
                handwritten=handwritten,
                ocr_text=crop_ocr_text or ocr_text,
                classifier_confident=classifier_confident,
                form_type=form_type.value,
                health_fund=health_fund,
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
                source=(
                    "ocr"
                    if crop_ocr_text and not handwritten and ocr_agrees(value or [], crop_ocr_text)
                    else "vlm"
                ),
            )
        extractions.append(
            FormExtraction(form_type=form_type.value, page=page.number, fields=fields)
        )
    return extractions
