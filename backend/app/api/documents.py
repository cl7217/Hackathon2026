import uuid
from pathlib import Path


from fastapi import APIRouter, BackgroundTasks, File, HTTPException, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from app.config import (
    DATA_DIR,
    FIELD_NAMES,
    MAX_BATCH_BYTES,
    MAX_BATCH_FILES,
    MAX_UPLOAD_BYTES,
)
from app.pipeline.extractor import ExtractorUnavailableError
from app.pipeline.ingest import InvalidDocumentError
from app.pipeline.process import extract_document
from app.services.database import (
    approve_document,
    create_batch,
    correct_field,
    delete_document_form,
    list_records,
    read_batch,
    review_field,
    save_extraction,
    update_batch_status,
)
from app.services.excel import build_approved_workbook
from app.services.jobs import process_batch
from app.services.previews import cache_document_pages, get_document_page

router = APIRouter()


def _safe_filename(filename: str | None) -> str:
    return (filename or "").replace("\\", "/").rsplit("/", 1)[-1]


class FieldCorrection(BaseModel):
    value: str | list[str] | None


class FieldsCorrection(BaseModel):
    page: int = Field(default=1, ge=1)
    fields: dict[str, str | list[str] | None]


@router.get("/")
def read_root() -> dict[str, str]:
    return {"message": "מערכת חילוץ הנתונים פועלת"}


@router.post("/extract")
@router.post("/api/extract/")
async def extract_document_endpoint(file: UploadFile = File(...)) -> dict:
    filename = _safe_filename(file.filename)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="קובץ חורג ממגבלת 20MB.")
    try:
        rendered_pages = []
        extractions = await run_in_threadpool(
            extract_document,
            filename,
            content,
            on_page_rendered=rendered_pages.append,
        )
        batch_id, document_id = await run_in_threadpool(save_extraction, filename, extractions)
        cache_document_pages(document_id, rendered_pages)
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
@router.post("/api/documents/upload", status_code=202)
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
@router.get("/api/documents/batch/{batch_id}")
def get_batch(batch_id: str) -> dict:
    batch = read_batch(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="האצווה לא נמצאה.")
    return batch


@router.get("/api/documents/{document_id}/pages/{page}/image")
def get_document_page_image(document_id: str, page: int) -> Response:
    if page < 1:
        raise HTTPException(status_code=400, detail="מספר העמוד אינו תקין.")
    image = get_document_page(document_id, page)
    if image is None:
        raise HTTPException(status_code=404, detail="תצוגת העמוד אינה זמינה בזיכרון.")
    return Response(content=image, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.get("/api/records")
def get_records(
    search: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None),
    approved: bool | None = Query(default=None),
    sender: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    allowed_statuses = {"queued", "processing", "complete", "partial", "failed"}
    if status is not None and status not in allowed_statuses:
        raise HTTPException(status_code=400, detail="מצב הרשומה אינו תקין.")
    return list_records(
        search=search,
        status=status,
        approved=approved,
        sender=sender,
        limit=limit,
        offset=offset,
    )


@router.patch("/api/documents/{document_id}/fields/{field_name}")
def update_field(
    document_id: str,
    field_name: str,
    correction: FieldCorrection,
    page: int = Query(default=1, ge=1),
) -> dict[str, bool]:
    if field_name not in FIELD_NAMES:
        raise HTTPException(status_code=400, detail="שם השדה אינו נתמך.")
    if not correct_field(document_id, field_name, correction.value, page):
        raise HTTPException(status_code=404, detail="המסמך או השדה לא נמצאו.")
    return {"updated": True}


@router.patch("/api/documents/{document_id}/fields")
def update_fields(document_id: str, correction: FieldsCorrection) -> dict[str, list[str]]:
    if not correction.fields:
        raise HTTPException(status_code=400, detail="יש לציין לפחות שדה אחד לעדכון.")
    unknown_fields = set(correction.fields) - set(FIELD_NAMES)
    if unknown_fields:
        raise HTTPException(status_code=400, detail="נשלחו שמות שדות שאינם נתמכים.")
    updated = []
    for field_name, value in correction.fields.items():
        if not correct_field(document_id, field_name, value, correction.page):
            raise HTTPException(status_code=404, detail=f"השדה {field_name} לא נמצא.")
        updated.append(field_name)
    return {"updated": updated}


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
