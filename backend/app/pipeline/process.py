from collections.abc import Callable
import logging
import time

from app.config import FIELD_NAMES
from app.pipeline.classify import classify_form
from app.pipeline.confidence import evaluate_field
from app.pipeline.ingest import PageImage, render_document
from app.pipeline.local_extractor import read_ocr
from app.pipeline.gemini_extractor import GeminiExtractor
from app.pipeline.normalize import (
    normalize_date,
    normalize_id_number,
    normalize_identifier_list,
    normalize_text,
)
from app.pipeline.extractor import ExtractorUnavailableError
from app.schemas.extraction import ExtractedField, FormExtraction

logger = logging.getLogger("pipeline_logger")

# אתחול עצל: מפתח חסר לא יפיל את הייבוא של המודול.
# כשל Gemini לא מפעיל מנוע חלופי.
_EXTRACTOR: GeminiExtractor | None = None


def _get_extractor() -> GeminiExtractor:
    global _EXTRACTOR

    if _EXTRACTOR is None:
        _EXTRACTOR = GeminiExtractor()

    return _EXTRACTOR


def _normalize_candidate(
    name: str,
    field: dict,
) -> tuple[str | list[str] | None, bool]:
    raw_value = field.get("value")

    if isinstance(raw_value, list):
        candidates = [
            str(item)
            for item in raw_value
            if item is not None
        ]
    elif raw_value is None:
        candidates = []
    else:
        candidates = [str(raw_value)]

    handwritten = field.get("handwritten") is True

    if name in {"center_number", "commitment_number"}:
        values = normalize_identifier_list(candidates)
        return values or None, handwritten

    if name == "id_number":
        value = normalize_id_number(candidates[0]) if candidates else None
        return value, handwritten

    if name == "document_date":
        value, _ = normalize_date(
            candidates[0] if candidates else None
        )
        return value, handwritten

    if name in {
        "first_name",
        "last_name",
        "sender",
        "health_fund",
        "received_stamp",
    }:
        value = normalize_text(candidates[0]) if candidates else None
        return value, handwritten

    return None, handwritten


def _valid_bbox(
    bbox: object,
    *,
    width: int,
    height: int,
) -> list[int] | None:
    if not isinstance(bbox, list) or len(bbox) != 4:
        return None

    # bool הוא תת-מחלקה של int בפייתון, לכן נדרשת בדיקה מדויקת.
    if any(type(coordinate) is not int for coordinate in bbox):
        return None

    x1, y1, x2, y2 = bbox

    if (
        x1 < 0
        or y1 < 0
        or x2 > width
        or y2 > height
        or x2 <= x1
        or y2 <= y1
    ):
        return None

    return bbox


def _empty_fields() -> dict:
    """Create null-valued fields for a document that needs review."""
    return {
        name: ExtractedField(
            value=None,
            page=0,
            bbox=None,
            raw=None,
            confidence=0.0,
            state="orange",
            needs_review=True,
            signals=["extraction_failed"],
            handwritten=False,
            source="vlm",
        )
        for name in FIELD_NAMES
    }


def extract_document(
    filename: str,
    content: bytes,
    on_stage: Callable[[str], None] | None = None,
    on_page_rendered: Callable[[PageImage], None] | None = None,
) -> list[FormExtraction]:
    pipeline_start_time = time.time()

    logger.info(
        "[PIPELINE START] Processing document: %s; bytes=%d",
        filename,
        len(content),
    )

    def report_stage(stage: str) -> None:
        if on_stage:
            on_stage(stage)

    # ----------------------------------------------------
    # Stage 1: Ingestion and rendering
    # ----------------------------------------------------
    stage_start = time.time()
    report_stage("ingestion")

    try:
        pages = render_document(filename, content)

        if not pages:
            raise ValueError("Document contains no renderable pages.")

        logger.info(
            "[INGEST] Rendered %d pages in %.2fs",
            len(pages),
            time.time() - stage_start,
        )
    except Exception:
        logger.exception("[INGEST] Document rendering failed")
        raise

    if on_page_rendered:
        for page in pages:
            on_page_rendered(page)

    extractions: list[FormExtraction] = []

    # ----------------------------------------------------
    # Process each page independently
    # ----------------------------------------------------
    for page in pages:
        page_start_time = time.time()

        logger.info(
            "[PAGE START] page=%d/%d",
            page.number,
            len(pages),
        )

        # ------------------------------------------------
        # Stage 2: OCR and classification
        # ------------------------------------------------
        report_stage("classification")
        stage_start = time.time()

        try:
            ocr_text = read_ocr(page.png)

            if not isinstance(ocr_text, str) or not ocr_text.strip():
                raise ValueError("OCR returned empty text.")

            form_type, classifier_confident = classify_form(ocr_text)

        except Exception:
            logger.exception(
                "[CLASSIFY] OCR or form classification failed; "
                "page=%d requires manual review",
                page.number,
            )

            # לא מנחשים סוג טופס ולא שולחים טקסט ריק למודל.
            extractions.append(
                FormExtraction(
                    form_type="unknown",
                    page=page.number,
                    fields=_empty_fields(),
                )
            )
            report_stage("manual_review")
            continue

        logger.info(
            "[CLASSIFY] page=%d; type=%s; confident=%s; "
            "ocr_chars=%d; duration=%.2fs",
            page.number,
            form_type.value,
            classifier_confident,
            len(ocr_text),
            time.time() - stage_start,
        )

        # ------------------------------------------------
        # Stage 3: Gemini extraction
        # ------------------------------------------------
        report_stage("extraction")
        stage_start = time.time()

        try:
            candidate = _get_extractor().extract(
                page.png,
                form_type=form_type.value,
                ocr_text=ocr_text,
                width=page.width,
                height=page.height,
            )

            if not isinstance(candidate.fields, dict):
                raise ExtractorUnavailableError(
                    "Gemini returned an invalid extraction structure."
                )

            logger.info(
                "[EXTRACT] page=%d; duration=%.2fs",
                page.number,
                time.time() - stage_start,
            )

        except Exception:
            logger.exception(
                "[EXTRACT] Gemini extraction failed; "
                "page=%d requires manual review",
                page.number,
            )

            # אין fallback למודל אחר ואין אישור אוטומטי.
            extractions.append(
                FormExtraction(
                    form_type=form_type.value,
                    page=page.number,
                    fields=_empty_fields(),
                )
            )
            report_stage("manual_review")
            continue

        # ------------------------------------------------
        # Stage 4: Business validation and normalization
        # ------------------------------------------------
        stage_start = time.time()

        candidate_fields = candidate.fields

        # Normalization of the health fund for cross-field validation.
        health_fund_raw = candidate_fields.get("health_fund")
        health_fund_value, _ = _normalize_candidate(
            "health_fund",
            health_fund_raw
            if isinstance(health_fund_raw, dict)
            else {},
        )

        if isinstance(health_fund_value, list):
            health_fund_value = (
                health_fund_value[0]
                if health_fund_value
                else None
            )

        fields = {}
        typed_ocr_text = read_ocr(page.png)

        for name in FIELD_NAMES:
            report_stage("validation")
            item = candidate_fields.get(name)

            if not isinstance(item, dict):
                item = {}

            bbox = _valid_bbox(
                item.get("bbox"),
                width=page.width,
                height=page.height,
            )

            value, handwritten = _normalize_candidate(name, item)
            field_source = "ocr"

            if handwritten and bbox is not None:
                try:
                    crop_result = _get_extractor().extract_field_crop(
                        page.png,
                        field_name=name,
                        bbox=bbox,
                        width=page.width,
                        height=page.height,
                    )
                    if isinstance(crop_result, dict):
                        value = crop_result.get("value")
                        raw = crop_result.get("raw")
                        if isinstance(raw, str):
                            raw = raw
                        else:
                            raw = item.get("raw") if isinstance(item.get("raw"), str) else None
                        if value is not None and isinstance(value, list):
                            value = normalize_identifier_list(value) if name in {"center_number", "commitment_number"} else value
                        if isinstance(value, str):
                            value = value.strip() or None
                        if value is None:
                            value, handwritten = _normalize_candidate(name, item)
                        field_source = "vlm"
                    else:
                        field_source = "ocr"
                except Exception:
                    logger.exception(
                        "[CROP] Failed to inspect handwritten field=%s page=%d",
                        name,
                        page.number,
                    )
                    value, handwritten = _normalize_candidate(name, item)
                    field_source = "ocr"
            else:
                raw = item.get("raw")
                if not isinstance(raw, str):
                    raw = None

            if not handwritten:
                value, _ = _normalize_candidate(name, item)
                raw = item.get("raw") if isinstance(item.get("raw"), str) else None

            if handwritten and field_source == "vlm":
                raw = item.get("raw") if isinstance(item.get("raw"), str) else None

            try:
                state, confidence, signals = evaluate_field(
                    name,
                    value,
                    page=page.number,
                    bbox=bbox,
                    handwritten=handwritten,
                    ocr_text=typed_ocr_text,
                    classifier_confident=classifier_confident,
                    form_type=form_type.value,
                    health_fund=health_fund_value,
                )
            except Exception:
                logger.exception(
                    "[VALIDATION] Validation failed for field=%s "
                    "page=%d",
                    name,
                    page.number,
                )

                state = "orange"
                confidence = 0.0
                signals = ["validation_failed"]

            # Do not log patient data or extracted field values.
            logger.info(
                "[FIELD] page=%d; field=%s; state=%s; "
                "confidence=%.2f; handwritten=%s",
                page.number,
                name,
                state,
                confidence,
                handwritten,
            )

            fields[name] = ExtractedField(
                value=value,
                page=page.number,
                bbox=bbox,
                raw=raw,
                confidence=confidence,
                state=state,
                needs_review=(state != "green"),
                signals=signals,
                handwritten=handwritten,
                source=field_source,
            )

        logger.info(
            "[VALIDATION] page=%d; duration=%.2fs",
            page.number,
            time.time() - stage_start,
        )

        # ------------------------------------------------
        # Stage 5: Prepare result for persistence/dashboard
        # ------------------------------------------------
        extractions.append(
            FormExtraction(
                form_type=form_type.value,
                page=page.number,
                fields=fields,
            )
        )

        logger.info(
            "[PAGE COMPLETE] page=%d; duration=%.2fs",
            page.number,
            time.time() - page_start_time,
        )

    logger.info(
        "[PIPELINE COMPLETE] pages=%d; duration=%.2fs",
        len(pages),
        time.time() - pipeline_start_time,
    )

    return extractions