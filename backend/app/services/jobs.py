from pathlib import Path
import logging
import time

from app.pipeline.extractor import ExtractorUnavailableError
from app.pipeline.ingest import InvalidDocumentError
from app.pipeline.process import extract_document
from app.services.audit import record_event
from app.services.database import (
    save_document_error,
    save_extraction,
    update_batch_progress,
    update_batch_status,
)
from app.services.previews import cache_document_pages

logger = logging.getLogger(__name__)


def process_batch(batch_id: str, uploads: list[tuple[str, str, str]]) -> None:
    update_batch_status(batch_id, "processing")
    record_event(
        "batch.processing_started",
        function="process_batch",
        batch_id=batch_id,
        status="processing",
        details={"document_count": len(uploads)},
    )
    succeeded = 0
    failed = 0
    trace_ids_by_path = {}
    try:
        for index, (filename, temporary_path, trace_id) in enumerate(uploads, start=1):
            trace_ids_by_path[temporary_path] = trace_id
            document_start = time.time()
            record_event(
                "document.queue_processing_started",
                function="process_batch",
                trace_id=trace_id,
                batch_id=batch_id,
                details={
                    "document_index": index,
                    "file_extension": Path(filename).suffix.lower(),
                },
            )
            try:
                content = Path(temporary_path).read_bytes()
                record_event(
                    "document.queue_file_read",
                    function="Path.read_bytes",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    status="success",
                    details={"file_bytes": len(content)},
                )
                rendered_pages = []
                extractions = extract_document(
                    filename,
                    content,
                    on_stage=lambda stage: _update_progress(
                        batch_id, trace_id, stage
                    ),
                    on_page_rendered=rendered_pages.append,
                    trace_id=trace_id,
                    batch_id=batch_id,
                )
                record_event(
                    "document.persistence_started",
                    function="save_extraction",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    details={"form_count": len(extractions)},
                )
                update_batch_progress(batch_id, "persistence")
                _, document_id = save_extraction(filename, extractions, batch_id=batch_id)
                record_event(
                    "document.persisted",
                    function="save_extraction",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    document_id=document_id,
                    status="success",
                    details={"form_count": len(extractions)},
                )
                update_batch_progress(batch_id, "review")
                preview_start = time.time()
                cache_document_pages(document_id, rendered_pages)
                record_event(
                    "document.preview_cached",
                    function="cache_document_pages",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    document_id=document_id,
                    status="success",
                    duration_ms=round((time.time() - preview_start) * 1000),
                    details={"page_count": len(rendered_pages)},
                )
                record_event(
                    "document.completed",
                    function="process_batch",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    document_id=document_id,
                    status="success",
                    duration_ms=round((time.time() - document_start) * 1000),
                )
                succeeded += 1
            except InvalidDocumentError as error:
                record_event(
                    "document.failed",
                    function="process_batch",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    status="failed",
                    duration_ms=round((time.time() - document_start) * 1000),
                    details={"error_type": type(error).__name__},
                )
                save_document_error(batch_id, filename, "הקובץ לא תקין או שאינו נתמך.")
                failed += 1
            except ExtractorUnavailableError as error:
                record_event(
                    "document.failed",
                    function="process_batch",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    status="failed",
                    duration_ms=round((time.time() - document_start) * 1000),
                    details={"error_type": type(error).__name__},
                )
                save_document_error(batch_id, filename, "מנוע החילוץ אינו זמין.")
                failed += 1
            except Exception as error:
                record_event(
                    "document.failed",
                    function="process_batch",
                    trace_id=trace_id,
                    batch_id=batch_id,
                    status="failed",
                    duration_ms=round((time.time() - document_start) * 1000),
                    details={"error_type": type(error).__name__},
                )
                logger.exception("Document processing failed.")
                save_document_error(batch_id, filename, "אירעה שגיאה בעיבוד המסמך.")
                failed += 1
    finally:
        for _, temporary_path, _ in uploads:
            temporary_file = Path(temporary_path)
            existed = temporary_file.exists()
            temporary_file.unlink(missing_ok=True)
            record_event(
                "queue.file_cleanup",
                function="Path.unlink",
                trace_id=trace_ids_by_path.get(temporary_path),
                batch_id=batch_id,
                status="success",
                details={"file_removed": existed},
            )
    if failed and succeeded:
        update_batch_status(batch_id, "partial")
    elif failed:
        update_batch_status(batch_id, "failed")
    else:
        update_batch_status(batch_id, "complete")
    record_event(
        "batch.processing_completed",
        function="process_batch",
        batch_id=batch_id,
        status="partial" if failed and succeeded else "failed" if failed else "complete",
        details={"succeeded": succeeded, "failed": failed},
    )


def _update_progress(batch_id: str, trace_id: str, stage: str) -> None:
    update_batch_progress(batch_id, stage)
    record_event(
        "batch.progress_updated",
        function="update_batch_progress",
        trace_id=trace_id,
        batch_id=batch_id,
        status=stage,
        details={"stage": stage},
    )
