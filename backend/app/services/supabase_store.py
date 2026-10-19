import json
import logging
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

from app.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL
from app.pipeline.confidence import validate_user_value
from app.schemas.extraction import FormExtraction

logger = logging.getLogger(__name__)
_PAGE_SIZE = 1000
_FILTER_CHUNK_SIZE = 200



def initialize_database() -> None:
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be configured."
        )
    if not SUPABASE_URL.startswith(("https://", "http://")):
        raise RuntimeError("SUPABASE_URL must be an HTTP(S) URL.")

    tables = {
        "extraction_batches": "id",
        "extraction_documents": "id",
        "extraction_forms": "id",
        "extraction_fields": "form_id",
    }

    for table, column in tables.items():
        result = _request(
            "GET",
            table,
            params={"select": column, "limit": "1"},
        )
        if not isinstance(result, list):
            raise RuntimeError(
                f"Supabase returned an invalid {table} readiness response."
            )


def _request(
    method: str,
    path: str,
    *,
    params: dict | None = None,
    payload: dict | list | None = None,
    prefer: str | None = None,
    row_range: tuple[int, int] | None = None,
) -> list | dict | None:
    query = urllib.parse.urlencode(params or {}, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if query:
        url = f"{url}?{query}"
    headers = {
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "Accept": "application/json",
    }
    if payload is not None:
        headers["Content-Type"] = "application/json"
    if prefer:
        headers["Prefer"] = prefer
    if row_range is not None:
        headers["Range-Unit"] = "items"
        headers["Range"] = f"{row_range[0]}-{row_range[1]}"
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read()
    
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        logger.error(
            "Supabase request failed: HTTP %s. URL: %s. Response: %s",
            error.code,
            request.full_url,
            body,
        )
        raise RuntimeError(
            f"Supabase request failed with HTTP {error.code}: {body}"
        ) from error

    except urllib.error.URLError as error:
        logger.error("Supabase request could not reach the configured service: %s", error)
        raise RuntimeError("Could not connect to the configured Supabase service.") from error
    if not response_body:
        return None
    try:
        result = json.loads(response_body)
    except json.JSONDecodeError as error:
        raise RuntimeError("Supabase returned an invalid JSON response.") from error
    if not isinstance(result, (dict, list)):
        raise RuntimeError("Supabase returned an unexpected response.")
    return result


def _rows(
    table: str,
    params: dict | None = None,
) -> list[dict]:
    result = []
    start = 0
    while True:
        page = _request(
            "GET",
            table,
            params={**(params or {}), "select": "*"},
            row_range=(start, start + _PAGE_SIZE - 1),
        )
        if not isinstance(page, list):
            raise RuntimeError(f"Supabase returned an invalid {table} response.")
        result.extend(page)
        if len(page) < _PAGE_SIZE:
            return result
        start += _PAGE_SIZE


def _rows_for_ids(
    table: str,
    column: str,
    ids: list[str],
    params: dict | None = None,
) -> list[dict]:
    rows = []
    for start in range(0, len(ids), _FILTER_CHUNK_SIZE):
        chunk = ids[start : start + _FILTER_CHUNK_SIZE]
        rows.extend(
            _rows(
                table,
                {
                    **(params or {}),
                    column: f"in.({','.join(chunk)})",
                },
            )
        )
    return rows


def _insert(table: str, values: dict | list[dict]) -> list[dict]:
    result = _request(
        "POST",
        table,
        params={"select": "*"},
        payload=values,
        prefer="return=representation",
    )
    if not isinstance(result, list):
        raise RuntimeError(f"Supabase did not confirm insertion into {table}.")
    return result


def _patch(table: str, filters: dict, values: dict) -> list[dict]:
    result = _request(
        "PATCH",
        table,
        params={**filters, "select": "*"},
        payload=values,
        prefer="return=representation",
    )
    if not isinstance(result, list):
        raise RuntimeError(f"Supabase returned an invalid update response for {table}.")
    return result


def _new_id() -> str:
    return str(uuid.uuid4())


def create_batch(status: str = "queued") -> str:
    batch_id = _new_id()
    _insert(
        "extraction_batches",
        {"id": batch_id, "created_at": datetime.now(timezone.utc).isoformat(), "status": status},
    )
    return batch_id


def update_batch_status(batch_id: str, status: str) -> None:
    stage = (
        "review"
        if status in {"complete", "partial", "failed"}
        else "ingestion"
    )
    if not _patch(
        "extraction_batches",
        {"id": f"eq.{batch_id}"},
        {"status": status, "stage": stage},
    ):
        raise RuntimeError("The extraction batch was not found in Supabase.")


def update_batch_progress(batch_id: str, stage: str) -> None:
    if stage not in {"ingestion", "classification", "extraction", "validation", "persistence", "review"}:
        raise ValueError("Unsupported extraction pipeline stage.")
    if not _patch(
        "extraction_batches",
        {"id": f"eq.{batch_id}"},
        {"stage": stage},
    ):
        raise RuntimeError("The extraction batch was not found in Supabase.")


def save_extraction(
    filename: str, extractions: list[FormExtraction], batch_id: str | None = None
) -> tuple[str, str]:
    new_batch = batch_id is None
    batch_id = batch_id or create_batch(status="processing")
    document_id = _new_id()
    forms = [
        {
            "id": _new_id(),
            "form_type": extraction.form_type,
            "page": extraction.page,
            "fields": {
                name: field.model_dump(mode="json")
                for name, field in extraction.fields.items()
            },
        }
        for extraction in extractions
    ]
    result = _request(
        "POST",
        "rpc/save_extraction",
        payload={
            "p_batch_id": batch_id,
            "p_document_id": document_id,
            "p_filename": filename,
            "p_forms": forms,
        },
    )
    if result != {"saved": True}:
        raise RuntimeError("Supabase did not confirm saving the extracted document.")
    if new_batch:
        update_batch_status(batch_id, "complete")
    return batch_id, document_id


def save_document_error(batch_id: str, filename: str, detail: str) -> None:
    _insert(
        "extraction_documents",
        {
            "id": _new_id(),
            "batch_id": batch_id,
            "filename": filename,
            "status": "failed",
            "error": detail,
            "approved": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )


def _fields_by_form(forms: list[dict]) -> dict[str, list[dict]]:
    form_ids = [form["id"] for form in forms]
    if not form_ids:
        return {}
    rows = _rows_for_ids(
        "extraction_fields",
        "form_id",
        form_ids,
        {"order": "name.asc"},
    )
    fields_by_form: dict[str, list[dict]] = {form_id: [] for form_id in form_ids}
    for row in rows:
        fields_by_form[row["form_id"]].append(
            {
                "name": row["name"],
                "value": row["value_json"],
                "raw": row["raw"],
                "page": row["page"],
                "bbox": row["bbox_json"],
                "source": row["source"],
                "confidence": row["confidence"],
                "state": row["state"],
                "needs_review": row["state"] != "green",
                "signals": row["signals_json"],
                "handwritten": bool(row["handwritten"]),
                "corrected_by_user": bool(row["corrected_by_user"]),
            }
        )
    return fields_by_form


def read_batch(batch_id: str) -> dict | None:
    batches = _rows("extraction_batches", {"id": f"eq.{batch_id}"})
    if not batches:
        return None
    batch = batches[0]
    documents = _rows(
        "extraction_documents",
        {"batch_id": f"eq.{batch_id}", "order": "created_at.asc"},
    )
    document_ids = [document["id"] for document in documents]
    forms_by_document: dict[str, list[dict]] = {document_id: [] for document_id in document_ids}
    if document_ids:
        forms = _rows_for_ids(
            "extraction_forms",
            "document_id",
            document_ids,
            {"order": "page.asc"},
        )
        fields_by_form = _fields_by_form(forms)
        for form in forms:
            forms_by_document[form["document_id"]].append(
                {
                    "id": form["id"],
                    "form_type": form["form_type"],
                    "page": form["page"],
                    "approved": bool(form["approved"]),
                    "fields": fields_by_form[form["id"]],
                }
            )
    return {
        "id": batch["id"],
        "created_at": batch["created_at"],
        "status": batch["status"],
        "stage": batch["stage"],
        "documents": [
            {
                "id": document["id"],
                "filename": document["filename"],
                "status": document["status"],
                "error": document.get("error"),
                "approved": bool(document["approved"]),
                "forms": forms_by_document[document["id"]],
            }
            for document in documents
        ],
    }


def _get_document_forms(document_id: str) -> list[dict]:
    forms = _rows(
        "extraction_forms",
        {"document_id": f"eq.{document_id}", "order": "page.asc"},
    )
    fields_by_form = _fields_by_form(forms)
    return [{**form, "fields": fields_by_form[form["id"]]} for form in forms]


def _update_field(
    document_id: str,
    field_name: str,
    page: int,
    *,
    value: str | list[str] | None = None,
    reviewed: bool,
) -> bool:
    forms = _rows(
        "extraction_forms",
        {"document_id": f"eq.{document_id}", "page": f"eq.{page}"},
    )
    if not forms:
        return False
    form = forms[0]
    field_rows = _rows(
        "extraction_fields",
        {"form_id": f"eq.{form['id']}", "name": f"eq.{field_name}"},
    )
    if not field_rows:
        return False
    health_fund_rows = _rows(
        "extraction_fields",
        {"form_id": f"eq.{form['id']}", "name": "eq.health_fund"},
    )
    health_fund = health_fund_rows[0]["value_json"] if health_fund_rows else None
    if isinstance(health_fund, list):
        health_fund = health_fund[0] if health_fund else None
    state, confidence, signals = validate_user_value(
        field_name, value, form["form_type"], health_fund
    )
    updates = {
        "state": state,
        "confidence": confidence,
        "signals_json": signals,
        "source": "user",
        "corrected_by_user": True,
    }
    if not reviewed:
        updates["value_json"] = value
    _patch(
        "extraction_fields",
        {"form_id": f"eq.{form['id']}", "name": f"eq.{field_name}"},
        updates,
    )
    _patch("extraction_forms", {"id": f"eq.{form['id']}"}, {"approved": False})
    if not _patch(
        "extraction_documents",
        {"id": f"eq.{document_id}"},
        {"approved": False},
    ):
        raise RuntimeError("The document was not found while updating its field.")
    return True


def correct_field(
    document_id: str, field_name: str, value: str | list[str] | None, page: int = 1
) -> bool:
    return _update_field(document_id, field_name, page, value=value, reviewed=False)


def review_field(document_id: str, field_name: str, page: int = 1) -> bool:
    return _update_field(document_id, field_name, page, reviewed=True)


def delete_document_form(document_id: str, page: int) -> bool:
    forms = _rows(
        "extraction_forms",
        {"document_id": f"eq.{document_id}", "page": f"eq.{page}"},
    )
    if not forms:
        return False
    _request(
        "DELETE",
        "extraction_forms",
        params={"id": f"eq.{forms[0]['id']}"},
        prefer="return=minimal",
    )
    remaining = _get_document_forms(document_id)
    if not remaining:
        _request(
            "DELETE",
            "extraction_documents",
            params={"id": f"eq.{document_id}"},
            prefer="return=minimal",
        )
    else:
        document_approved = all(form["approved"] for form in remaining)
        _patch(
            "extraction_documents",
            {"id": f"eq.{document_id}"},
            {"approved": document_approved},
        )
    return True


def approve_document(document_id: str, page: int | None = None) -> tuple[bool, str | None]:
    documents = _rows("extraction_documents", {"id": f"eq.{document_id}"})
    if not documents:
        return False, "not_found"
    forms = _get_document_forms(document_id)
    selected = [form for form in forms if page is None or form["page"] == page]
    if not selected or any(
        any(field.get("state") != "green" for field in form["fields"])
        for form in selected
    ):
        return False, "review_required"
    for form in selected:
        _patch("extraction_forms", {"id": f"eq.{form['id']}"}, {"approved": True})
    refreshed_forms = _get_document_forms(document_id)
    all_approved = bool(refreshed_forms) and all(
        form["approved"] for form in refreshed_forms
    )
    _patch(
        "extraction_documents",
        {"id": f"eq.{document_id}"},
        {"approved": all_approved},
    )
    return True, None


def approved_rows(document_ids: list[str] | None = None) -> list[dict]:
    if document_ids == []:
        return []
    documents = (
        _rows("extraction_documents", {"approved": "eq.true"})
        if document_ids is None
        else _rows_for_ids("extraction_documents", "id", document_ids)
    )
    documents_by_id = {
        document["id"]: document
        for document in documents
    }
    if not documents_by_id:
        return []
    forms = _rows_for_ids(
        "extraction_forms",
        "document_id",
        list(documents_by_id),
        {
            "approved": "eq.true",
            "order": "page.asc",
        },
    )
    fields_by_form = _fields_by_form(forms)
    output = []
    for form in forms:
        document = documents_by_id[form["document_id"]]
        output.append(
            {
                "filename": document["filename"],
                "form_type": form["form_type"],
                "page": form["page"],
                **{
                    field["name"]: field["value"]
                    for field in fields_by_form[form["id"]]
                },
            }
        )
    return output


def list_records(
    *,
    search: str | None = None,
    status: str | None = None,
    approved: bool | None = None,
    sender: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    documents = _rows("extraction_documents", {"order": "created_at.desc"})
    documents_by_id = {
        document["id"]: document
        for document in documents
        if status is None or document["status"] == status
    }
    if not documents_by_id:
        return {"records": [], "total": 0, "limit": limit, "offset": offset}
    forms = _rows_for_ids(
        "extraction_forms",
        "document_id",
        list(documents_by_id),
        {"order": "page.asc"},
    )
    fields_by_form = _fields_by_form(forms)
    search_text = (search or "").casefold().strip()
    sender_text = (sender or "").casefold().strip()
    records = []
    for form in forms:
        document = documents_by_id[form["document_id"]]
        if approved is not None and bool(form["approved"]) != approved:
            continue
        fields = fields_by_form[form["id"]]
        sender_value = next(
            (field["value"] for field in fields if field["name"] == "sender"), None
        )
        searchable = " ".join(
            [document["filename"], form["form_type"]]
            + [str(field.get("value") or "") for field in fields]
        ).casefold()
        if search_text and search_text not in searchable:
            continue
        normalized_sender_value = str(sender_value or "").casefold().strip()
        if sender_text and normalized_sender_value != sender_text:
            continue
        records.append(
            {
                "id": form["id"],
                "document_id": document["id"],
                "batch_id": document["batch_id"],
                "filename": document["filename"],
                "status": document["status"],
                "error": document.get("error"),
                "form_type": form["form_type"],
                "page": form["page"],
                "approved": bool(form["approved"]),
                "created_at": document["created_at"],
                "fields": fields,
            }
        )
    records.sort(
        key=lambda record: (record["created_at"], -record["page"]),
        reverse=True,
    )
    return {
        "records": records[offset : offset + limit],
        "total": len(records),
        "limit": limit,
        "offset": offset,
    }
