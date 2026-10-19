from pathlib import Path
import logging

from app.pipeline.extractor import ExtractorUnavailableError
from app.pipeline.ingest import InvalidDocumentError
from app.pipeline.process import extract_document
from app.services.database import (
    save_document_error,
    save_extraction,
    update_batch_progress,
    update_batch_status,
)
from app.services.previews import cache_document_pages

logger = logging.getLogger(__name__)


def process_batch(batch_id: str, uploads: list[tuple[str, str]]) -> None:
    update_batch_status(batch_id, "processing")
    succeeded = 0
    failed = 0
    try:
        for filename, temporary_path in uploads:
            try:
                content = Path(temporary_path).read_bytes()
                rendered_pages = []
                extractions = extract_document(
                    filename,
                    content,
                    on_stage=lambda stage: update_batch_progress(batch_id, stage),
                    on_page_rendered=rendered_pages.append,
                )
                update_batch_progress(batch_id, "persistence")
                _, document_id = save_extraction(filename, extractions, batch_id=batch_id)
                update_batch_progress(batch_id, "review")
                cache_document_pages(document_id, rendered_pages)
                succeeded += 1
            except InvalidDocumentError:
                save_document_error(batch_id, filename, "הקובץ לא תקין או שאינו נתמך.")
                failed += 1
            except ExtractorUnavailableError:
                save_document_error(batch_id, filename, "המודל המקומי אינו זמין.")
                failed += 1
            except Exception:
                logger.exception("Document processing failed.")
                save_document_error(batch_id, filename, "אירעה שגיאה בעיבוד המסמך.")
                failed += 1
    finally:
        for _, temporary_path in uploads:
            Path(temporary_path).unlink(missing_ok=True)
    if failed and succeeded:
        update_batch_status(batch_id, "partial")
    elif failed:
        update_batch_status(batch_id, "failed")
    else:
        update_batch_status(batch_id, "complete")
