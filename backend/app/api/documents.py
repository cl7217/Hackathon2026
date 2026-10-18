import uuid


from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import DATA_DIR, MAX_BATCH_BYTES, MAX_BATCH_FILES, MAX_UPLOAD_BYTES
from app.pipeline.extractor import ExtractorUnavailableError
from app.pipeline.ingest import InvalidDocumentError
from app.pipeline.process import extract_document
from app.services.database import (
    approve_document,
    create_batch,
    correct_field,
    delete_document_form,
    read_batch,
    review_field,
    save_extraction,
    update_batch_status,
)
from app.services.excel import build_approved_workbook
from app.services.jobs import process_batch

router = APIRouter()


def _safe_filename(filename: str | None) -> str:
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1]


class FieldCorrection(BaseModel):
    value: str | list[str] | None


@router.get("/")
def read_root() -> dict[str, str]:
    return {"message": "מערכת חילוץ הנתונים פועלת באופן מקומי"}


@router.post("/extract")
@router.post("/api/extract/")
async def extract_document_endpoint(file: UploadFile = File(...)) -> dict:
    filename = _safe_filename(file.filename)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        extractions = await run_in_threadpool(extract_document, filename, content)
        batch_id, document_id = await run_in_threadpool(save_extraction, filename, extractions)
    except InvalidDocumentError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except ExtractorUnavailableError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail="אירעה שגיאה בעיבוד המסמך.") from error

    first = extractions[0]
    return {
        "status": "success",
        "filename": filename,
        "batch_id": batch_id,
        "document_id": document_id,
        "data": first.frontend_data(),
        "forms": [form.frontend_data() for form in extractions],
    }


@router.post("/api/batches", status_code=202)
async def create_extraction_batch(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
) -> dict[str, str]:
    if not files:
        raise HTTPException(status_code=400, detail="יש לבחור לפחות קובץ אחד.")
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(status_code=413, detail="אצווה יכולה להכיל עד 50 קבצים.")
    contents = []
    total_size = 0
    for upload in files:
        filename = _safe_filename(upload.filename)
        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        total_size += len(content)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="קובץ חורג ממגבלת 20MB.")
        if total_size > MAX_BATCH_BYTES:
            raise HTTPException(status_code=413, detail="האצווה חורגת ממגבלת 100MB.")
        contents.append((filename, content))

    batch_id = create_batch()
    batch_dir = DATA_DIR / "queue"
    uploads = []
    try:
        batch_dir.mkdir(parents=True, exist_ok=True)
        for filename, content in contents:
            temporary_path = batch_dir / f"{uuid.uuid4()}.upload"
            uploads.append((filename, str(temporary_path)))
            temporary_path.write_bytes(content)
    except OSError as error:
        for _, temporary_path in uploads:
            Path(temporary_path).unlink(missing_ok=True)
        update_batch_status(batch_id, "failed")
        raise HTTPException(status_code=500, detail="לא ניתן לשמור את קובצי האצווה לעיבוד.") from error
    background_tasks.add_task(process_batch, batch_id, uploads)
    return {"batch_id": batch_id, "status": "queued"}


@router.get("/api/batches/{batch_id}")
def get_batch(batch_id: str) -> dict:
    batch = read_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="האצווה לא נמצאה.")
    return batch


@router.patch("/api/documents/{document_id}/fields/{field_name}")
def update_field(
    document_id: str,
    field_name: str,
    correction: FieldCorrection,
    page: int = Query(default=1, ge=1),
) -> dict[str, bool]:
    if not correct_field(document_id, field_name, correction.value, page):
        raise HTTPException(status_code=404, detail="המסמך או השדה לא נמצאו.")
    return {"updated": True}


@router.post("/api/documents/{document_id}/fields/{field_name}/review")
def mark_field_reviewed(
    document_id: str, field_name: str, page: int = Query(default=1, ge=1)
) -> dict[str, bool]:
    if not review_field(document_id, field_name, page):
        raise HTTPException(status_code=404, detail="המסמך או השדה לא נמצאו.")
    return {"reviewed": True}


@router.post("/api/documents/{document_id}/approve")
def approve(
    document_id: str, page: int | None = Query(default=None, ge=1)
) -> dict[str, bool]:
    approved, reason = approve_document(document_id, page)
    if reason == "not_found":
        raise HTTPException(status_code=404, detail="המסמך לא נמצא.")
    if not approved:
        raise HTTPException(status_code=409, detail="יש לבדוק את כל השדות לפני אישור המסמך.")
    return {"approved": True}


@router.delete("/api/documents/{document_id}")
def delete_form(document_id: str, page: int = Query(ge=1)) -> dict[str, bool]:
    if not delete_document_form(document_id, page):
        raise HTTPException(status_code=404, detail="המסמך או העמוד לא נמצאו.")
    return {"deleted": True}


@router.get("/api/export.xlsx")
def export_approved(document_ids: list[str] = Query(..., min_length=1)):
    workbook = build_approved_workbook(document_ids)
    return StreamingResponse(
        workbook,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="approved-forms.xlsx"'},
    )
