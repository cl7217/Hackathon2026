from pathlib import Path
import logging

from app.pipeline.extractor import ExtractorUnavailableError
from app.pipeline.ingest import InvalidDocumentError
from app.pipeline.process import extract_document
from app.services.database import (
    save_document_error,
    save_extraction,
    update_batch_status,
)

logger = logging.getLogger(__name__)


def process_batch(batch_id: str, uploads: list[tuple[str, str]]) -> None:
    update_batch_status(batch_id, "processing")
    succeeded = 0
    failed = 0
    try:
        for filename, temporary_path in uploads:
            try:
                content = Path(temporary_path).read_bytes()
                extractions = extract_document(filename, content)
                save_extraction(filename, extractions, batch_id=batch_id)
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
