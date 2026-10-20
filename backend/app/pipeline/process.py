from collections.abc import Callable
import logging
from pathlib import Path
import time
import uuid

from app.config import EXTRACTION_MODE, FIELD_NAMES, OCR_LANGUAGES
from app.pipeline.classify import FormType, classify_form
from app.pipeline.confidence import evaluate_field
from app.pipeline.extractor import (
    ExtractionCandidate,
    Extractor,
    ExtractorUnavailableError,
)
from app.pipeline.ingest import PageImage, render_document
from app.pipeline.ocr_extractor import OCRRulesExtractor, read_ocr
from app.pipeline.normalize import (
    normalize_date,
    normalize_id_number,
    normalize_identifier_list,
    normalize_text,
)
from app.schemas.extraction import ExtractedField, FormExtraction
from app.services.audit import record_event

logger = logging.getLogger("pipeline_logger")

# Gemini is only instantiated when explicitly selected or cross-checked.
_EXTRACTOR: OCRRulesExtractor | None = None
_GEMINI_EXTRACTOR = None


def _get_extractor(provider: str = "local_ocr_rules") -> Extractor:
    global _EXTRACTOR, _GEMINI_EXTRACTOR

    if provider == "gemini":
        if _GEMINI_EXTRACTOR is None:
            from app.pipeline.gemini_extractor import GeminiExtractor

            _GEMINI_EXTRACTOR = GeminiExtractor()
        return _GEMINI_EXTRACTOR
    if _EXTRACTOR is None:
        _EXTRACTOR = OCRRulesExtractor()
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


def _normalized_value(name: str, field: dict) -> str | tuple[str, ...] | None:
    value, _ = _normalize_candidate(name, field)
    if isinstance(value, list):
        return tuple(sorted(normalize_identifier_list(value)))
    return value


def _merge_candidates(
    local_candidate: ExtractionCandidate | None,
    gemini_candidate: ExtractionCandidate | None,
) -> ExtractionCandidate:
    if local_candidate is None and gemini_candidate is None:
        raise ExtractorUnavailableError("No extraction provider returned a result.")

    merged = {}
    for name in FIELD_NAMES:
        local_field = (
            local_candidate.fields.get(name, {})
            if local_candidate is not None
            else {}
        )
        gemini_field = (
            gemini_candidate.fields.get(name, {})
            if gemini_candidate is not None
            else {}
        )
        if not isinstance(local_field, dict):
            local_field = {}
        if not isinstance(gemini_field, dict):
            gemini_field = {}

        local_value = _normalized_value(name, local_field)
        gemini_value = _normalized_value(name, gemini_field)
        cross_check_complete = (
            local_candidate is not None and gemini_candidate is not None
        )
        agrees = (
            local_value == gemini_value
            if cross_check_complete
            else None
        )

        if local_value is not None:
            selected = dict(local_field)
            source = "local_ocr_rules"
        elif gemini_value is not None:
            selected = dict(gemini_field)
            source = "gemini"
        else:
            selected = dict(local_field or gemini_field)
            source = "local_ocr_rules" if local_candidate is not None else "gemini"

        other_field = gemini_field if source == "local_ocr_rules" else local_field
        for metadata_key in ("bbox", "raw"):
            if not selected.get(metadata_key) and other_field.get(metadata_key):
                selected[metadata_key] = other_field[metadata_key]
        selected["handwritten"] = (
            selected.get("handwritten") is True
            or other_field.get("handwritten") is True
        )
        selected["_engine_agreement"] = agrees
        selected["_engine_check_incomplete"] = not cross_check_complete
        selected["_engine_source"] = source
        merged[name] = selected

    return ExtractionCandidate(
        fields=merged,
        raw_response="",
    )


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
            signals={"extraction_failed": True},
            handwritten=False,
            source="ocr" if EXTRACTION_MODE == "local_ocr_rules" else "vlm",
        )
        for name in FIELD_NAMES
    }


def _audit_field_results(
    fields: dict[str, ExtractedField],
    *,
    trace_id: str,
    batch_id: str | None,
    page: int,
) -> None:
    for name, field in fields.items():
        record_event(
            "field.validated",
            function="evaluate_field",
            trace_id=trace_id,
            batch_id=batch_id,
            page=page,
            status=field.state,
            details={
                "field": name,
                "found": field.value is not None,
                "confidence": field.confidence,
                "handwritten": field.handwritten,
                "source": field.source,
                "signals": sorted(field.signals),
                "bbox_found": field.bbox is not None,
            },
        )


def extract_document(
    filename: str,
    content: bytes,
    on_stage: Callable[[str], None] | None = None,
    on_page_rendered: Callable[[PageImage], None] | None = None,
    *,
    trace_id: str | None = None,
    batch_id: str | None = None,
) -> list[FormExtraction]:
    pipeline_start_time = time.time()
    trace_id = trace_id or str(uuid.uuid4())

    logger.info(
        "[PIPELINE START] Processing document; extension=%s; bytes=%d",
        Path(filename).suffix.lower(),
        len(content),
    )
    record_event(
        "document.processing_started",
        function="extract_document",
        trace_id=trace_id,
        batch_id=batch_id,
        details={
            "file_extension": Path(filename).suffix.lower(),
            "file_bytes": len(content),
            "extraction_mode": EXTRACTION_MODE,
        },
    )

    def report_stage(stage: str) -> None:
        record_event(
            "pipeline.stage_started",
            function="extract_document",
            trace_id=trace_id,
            batch_id=batch_id,
            status=stage,
            details={"stage": stage},
        )
        if on_stage:
            on_stage(stage)

    # ----------------------------------------------------
    # Stage 1: Ingestion and rendering
    # ----------------------------------------------------
    stage_start = time.time()
    report_stage("ingestion")
    record_event(
        "document.render_started",
        function="render_document",
        trace_id=trace_id,
        batch_id=batch_id,
        details={"file_extension": Path(filename).suffix.lower()},
    )

    try:
        pages = render_document(filename, content)

        if not pages:
            raise ValueError("Document contains no renderable pages.")

        logger.info(
            "[INGEST] Rendered %d pages in %.2fs",
            len(pages),
            time.time() - stage_start,
        )
    except Exception as error:
        record_event(
            "document.render_failed",
            function="render_document",
            trace_id=trace_id,
            batch_id=batch_id,
            status="failed",
            duration_ms=round((time.time() - stage_start) * 1000),
            details={"error_type": type(error).__name__},
        )
        logger.exception("[INGEST] Document rendering failed")
        raise
    record_event(
        "document.rendered",
        function="render_document",
        trace_id=trace_id,
        batch_id=batch_id,
        status="success",
        duration_ms=round((time.time() - stage_start) * 1000),
        details={
            "page_count": len(pages),
            "render_dpi": 300 if Path(filename).suffix.lower() == ".pdf" else None,
        },
    )

    if on_page_rendered:
        for page in pages:
            on_page_rendered(page)
            record_event(
                "page.preview_ready",
                function="on_page_rendered",
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
                status="success",
                details={
                    "width": page.width,
                    "height": page.height,
                    "image_bytes": len(page.png),
                },
            )

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
        record_event(
            "page.ocr_started",
            function="read_ocr",
            trace_id=trace_id,
            batch_id=batch_id,
            page=page.number,
            details={"ocr_languages": OCR_LANGUAGES},
        )

        try:
            ocr_text = read_ocr(page.png)
            ocr_available = isinstance(ocr_text, str) and bool(ocr_text.strip())
            record_event(
                "page.ocr_completed",
                function="read_ocr",
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
                status="success" if ocr_available else "empty",
                duration_ms=round((time.time() - stage_start) * 1000),
                details={
                    "text_available": ocr_available,
                    "character_count": len(ocr_text) if isinstance(ocr_text, str) else 0,
                },
            )
            if not ocr_available and EXTRACTION_MODE == "local_ocr_rules":
                raise ValueError("OCR returned empty text.")
            if ocr_available:
                form_type, classifier_confident = classify_form(ocr_text)
            else:
                form_type, classifier_confident = FormType.UNKNOWN, False

        except Exception as error:
            record_event(
                "page.classification_failed",
                function="classify_form",
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
                status="failed",
                duration_ms=round((time.time() - stage_start) * 1000),
                details={"error_type": type(error).__name__},
            )
            logger.exception(
                "[CLASSIFY] OCR or form classification failed; "
                "page=%d requires manual review",
                page.number,
            )

            # לא מנחשים סוג טופס ולא שולחים טקסט ריק למודל.
            fields = _empty_fields()
            _audit_field_results(
                fields,
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
            )
            extractions.append(
                FormExtraction(form_type="unknown", page=page.number, fields=fields)
            )
            report_stage("manual_review")
            continue

        record_event(
            "page.classified",
            function="classify_form",
            trace_id=trace_id,
            batch_id=batch_id,
            page=page.number,
            status="success" if classifier_confident else "uncertain",
            duration_ms=round((time.time() - stage_start) * 1000),
            details={
                "form_type": form_type.value,
                "classification_confident": classifier_confident,
                "ocr_available": ocr_available,
            },
        )

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
        # Stage 3: configurable local, Gemini, or cross-checked extraction
        # ------------------------------------------------
        report_stage("extraction")
        stage_start = time.time()

        try:
            provider_results: dict[str, ExtractionCandidate | None] = {
                "local_ocr_rules": None,
                "gemini": None,
            }
            if EXTRACTION_MODE == "hybrid":
                providers = (
                    ("local_ocr_rules", "gemini")
                    if ocr_available
                    else ("gemini",)
                )
            else:
                providers = (EXTRACTION_MODE,)
            provider_errors = []
            for provider in providers:
                provider_start = time.time()
                record_event(
                    "provider.extraction_started",
                    function=f"{provider}.extract",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    page=page.number,
                    details={"provider": provider, "mode": EXTRACTION_MODE},
                )
                try:
                    result = _get_extractor(provider).extract(
                        page.png,
                        form_type=form_type.value,
                        ocr_text=ocr_text,
                        width=page.width,
                        height=page.height,
                    )
                    if not isinstance(result.fields, dict):
                        raise ExtractorUnavailableError(
                            f"{provider} returned an invalid extraction structure."
                        )
                    provider_results[provider] = result
                    found_fields = sorted(
                        name
                        for name, field in result.fields.items()
                        if isinstance(field, dict)
                        and (
                            field.get("value") is not None
                            and field.get("value") != ""
                            and field.get("value") != []
                        )
                    )
                    record_event(
                        "provider.extraction_completed",
                        function=f"{provider}.extract",
                        trace_id=trace_id,
                        batch_id=batch_id,
                        page=page.number,
                        status="success",
                        duration_ms=round((time.time() - provider_start) * 1000),
                        details={
                            "provider": provider,
                            "fields_found": found_fields,
                            "fields_missing": sorted(set(FIELD_NAMES) - set(found_fields)),
                            "handwritten_fields": sorted(
                                name
                                for name, field in result.fields.items()
                                if isinstance(field, dict)
                                and field.get("handwritten") is True
                                and name in FIELD_NAMES
                            ),
                        },
                    )
                except Exception as error:
                    record_event(
                        "provider.extraction_failed",
                        function=f"{provider}.extract",
                        trace_id=trace_id,
                        batch_id=batch_id,
                        page=page.number,
                        status="failed",
                        duration_ms=round((time.time() - provider_start) * 1000),
                        details={
                            "provider": provider,
                            "error_type": type(error).__name__,
                        },
                    )
                    logger.warning(
                        "[EXTRACT] Provider=%s failed; page=%d; error=%s",
                        provider,
                        page.number,
                        type(error).__name__,
                    )
                    provider_errors.append(provider)

            if EXTRACTION_MODE == "hybrid":
                candidate = _merge_candidates(
                    provider_results["local_ocr_rules"],
                    provider_results["gemini"],
                )
                if provider_errors:
                    logger.warning(
                        "[EXTRACT] Hybrid cross-check incomplete; page=%d; unavailable=%s",
                        page.number,
                        ",".join(provider_errors),
                    )
            else:
                candidate = provider_results[EXTRACTION_MODE]
                if candidate is None:
                    raise ExtractorUnavailableError(
                        f"The configured {EXTRACTION_MODE} extraction provider failed."
                    )

            logger.info(
                "[EXTRACT] mode=%s; page=%d; duration=%.2fs",
                EXTRACTION_MODE,
                page.number,
                time.time() - stage_start,
            )

        except Exception as error:
            record_event(
                "page.extraction_failed",
                function="extract_document",
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
                status="failed",
                duration_ms=round((time.time() - stage_start) * 1000),
                details={"error_type": type(error).__name__},
            )
            logger.exception(
                "[EXTRACT] Extraction failed; "
                "page=%d requires manual review",
                page.number,
            )

            # Never auto-approve a failed extraction or silently switch providers.
            fields = _empty_fields()
            _audit_field_results(
                fields,
                trace_id=trace_id,
                batch_id=batch_id,
                page=page.number,
            )
            extractions.append(
                FormExtraction(form_type=form_type.value, page=page.number, fields=fields)
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
        typed_ocr_text = ocr_text

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
            engine_agreement = item.get("_engine_agreement")
            engine_check_incomplete = item.get("_engine_check_incomplete") is True
            engine_source = item.get("_engine_source", EXTRACTION_MODE)
            field_source = "vlm" if engine_source == "gemini" else "ocr"

            if handwritten and bbox is not None:
                crop_start = time.time()
                try:
                    crop_provider = (
                        engine_source
                        if engine_source in {"local_ocr_rules", "gemini"}
                        else "local_ocr_rules"
                    )
                    record_event(
                        "field.crop_started",
                        function=f"{crop_provider}.extract_field_crop",
                        trace_id=trace_id,
                        batch_id=batch_id,
                        page=page.number,
                        details={
                            "field": name,
                            "provider": crop_provider,
                            "bbox_found": True,
                        },
                    )
                    crop_result = _get_extractor(crop_provider).extract_field_crop(
                        page.png,
                        field_name=name,
                        bbox=bbox,
                        width=page.width,
                        height=page.height,
                    )
                    if isinstance(crop_result, dict):
                        crop_value, crop_handwritten = _normalize_candidate(
                            name,
                            crop_result,
                        )
                        if crop_value is not None:
                            value = crop_value
                            handwritten = handwritten or crop_handwritten
                            field_source = (
                                "vlm" if crop_provider == "gemini" else "ocr"
                            )
                        crop_raw = crop_result.get("raw")
                        record_event(
                            "field.crop_completed",
                            function=f"{crop_provider}.extract_field_crop",
                            trace_id=trace_id,
                            batch_id=batch_id,
                            page=page.number,
                            status="found" if crop_value is not None else "empty",
                            duration_ms=round((time.time() - crop_start) * 1000),
                            details={
                                "field": name,
                                "found": crop_value is not None,
                                "handwritten": crop_handwritten,
                            },
                        )
                        raw = (
                            crop_raw
                            if isinstance(crop_raw, str)
                            else item.get("raw")
                            if isinstance(item.get("raw"), str)
                            else None
                        )
                    else:
                        record_event(
                            "field.crop_completed",
                            function=f"{crop_provider}.extract_field_crop",
                            trace_id=trace_id,
                            batch_id=batch_id,
                            page=page.number,
                            status="empty",
                            duration_ms=round((time.time() - crop_start) * 1000),
                            details={"field": name, "found": False},
                        )
                except Exception as error:
                    record_event(
                        "field.crop_failed",
                        function="extract_field_crop",
                        trace_id=trace_id,
                        batch_id=batch_id,
                        page=page.number,
                        status="failed",
                        duration_ms=round((time.time() - crop_start) * 1000),
                        details={
                            "field": name,
                            "error_type": type(error).__name__,
                        },
                    )
                    logger.exception(
                        "[CROP] Failed to inspect handwritten field=%s page=%d",
                        name,
                        page.number,
                    )
                    value, handwritten = _normalize_candidate(name, item)
                    raw = item.get("raw") if isinstance(item.get("raw"), str) else None
            else:
                raw = item.get("raw")
                if not isinstance(raw, str):
                    raw = None

            if not handwritten:
                value, _ = _normalize_candidate(name, item)
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
                if engine_agreement is not None:
                    signals["engine_agreement"] = engine_agreement
                if engine_check_incomplete:
                    signals["engine_check_incomplete"] = True
                if engine_agreement is False or engine_check_incomplete:
                    state = "orange"
                    confidence = min(confidence, 0.5)
            except Exception:
                logger.exception(
                    "[VALIDATION] Validation failed for field=%s "
                    "page=%d",
                    name,
                    page.number,
                )

                state = "orange"
                confidence = 0.0
                signals = {"validation_failed": True}

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

        _audit_field_results(
            fields,
            trace_id=trace_id,
            batch_id=batch_id,
            page=page.number,
        )
        record_event(
            "page.validation_completed",
            function="evaluate_field",
            trace_id=trace_id,
            batch_id=batch_id,
            page=page.number,
            status="success",
            duration_ms=round((time.time() - stage_start) * 1000),
            details={
                "fields_found": sum(field.value is not None for field in fields.values()),
                "fields_missing": sum(field.value is None for field in fields.values()),
                "fields_needing_review": sum(
                    field.needs_review for field in fields.values()
                ),
            },
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
        record_event(
            "page.processing_completed",
            function="extract_document",
            trace_id=trace_id,
            batch_id=batch_id,
            page=page.number,
            status="success",
            duration_ms=round((time.time() - page_start_time) * 1000),
            details={"form_type": form_type.value},
        )

    logger.info(
        "[PIPELINE COMPLETE] pages=%d; duration=%.2fs",
        len(pages),
        time.time() - pipeline_start_time,
    )
    record_event(
        "document.processing_completed",
        function="extract_document",
        trace_id=trace_id,
        batch_id=batch_id,
        status="success",
        duration_ms=round((time.time() - pipeline_start_time) * 1000),
        details={"page_count": len(pages), "form_count": len(extractions)},
    )

    return extractions