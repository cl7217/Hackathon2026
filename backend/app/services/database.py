import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from app.config import DATABASE_PATH, DATA_DIR, SUPABASE_ENABLED
from app.pipeline.confidence import validate_user_value
from app.schemas.extraction import FormExtraction


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            yield connection
    finally:
        connection.close()


def initialize_database() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS batches (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL DEFAULT 'ingestion'
            );
            CREATE TABLE IF NOT EXISTS documents (
                id TEXT PRIMARY KEY,
                batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                approved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS forms (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                form_type TEXT NOT NULL,
                page INTEGER NOT NULL,
                approved INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS fields (
                form_id TEXT NOT NULL REFERENCES forms(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                value_json TEXT,
                raw TEXT,
                page INTEGER,
                bbox_json TEXT,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                state TEXT NOT NULL,
                signals_json TEXT NOT NULL,
                handwritten INTEGER NOT NULL,
                corrected_by_user INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (form_id, name)
            );
            """
        )
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(documents)")
        }
        if "error" not in columns:
            connection.execute("ALTER TABLE documents ADD COLUMN error TEXT")
        form_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(forms)")
        }
        if "approved" not in form_columns:
            connection.execute(
                "ALTER TABLE forms ADD COLUMN approved INTEGER NOT NULL DEFAULT 0"
            )
        batch_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(batches)")
        }
        if "stage" not in batch_columns:
            connection.execute(
                "ALTER TABLE batches ADD COLUMN stage TEXT NOT NULL DEFAULT 'ingestion'"
            )


def create_batch(status: str = "queued") -> str:
    batch_id = str(uuid.uuid4())
    with _connect() as connection:
        connection.execute(
            "INSERT INTO batches (id, created_at, status, stage) VALUES (?, ?, ?, ?)",
            (
                batch_id,
                datetime.now(timezone.utc).isoformat(),
                status,
                "ingestion" if status in {"queued", "processing"} else "complete",
            ),
        )
    return batch_id


def update_batch_status(batch_id: str, status: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE batches SET status = ?, stage = ? WHERE id = ?",
            (status, "complete" if status in {"complete", "partial", "failed"} else "ingestion", batch_id),
        )


def update_batch_progress(batch_id: str, stage: str) -> None:
    with _connect() as connection:
        connection.execute(
            "UPDATE batches SET stage = ? WHERE id = ?",
            (stage, batch_id),
        )


def save_extraction(
    filename: str, extractions: list[FormExtraction], batch_id: str | None = None
) -> tuple[str, str]:
    new_batch = batch_id is None
    batch_id = batch_id or str(uuid.uuid4())
    document_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    with _connect() as connection:
        if new_batch:
            connection.execute(
                "INSERT INTO batches (id, created_at, status, stage) VALUES (?, ?, ?, ?)",
                (batch_id, now, "complete", "complete"),
            )
        connection.execute(
            "INSERT INTO documents (id, batch_id, filename, status, created_at) VALUES (?, ?, ?, ?, ?)",
            (document_id, batch_id, filename, "complete", now),
        )
        for extraction in extractions:
            form_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO forms (id, document_id, form_type, page) VALUES (?, ?, ?, ?)",
                (form_id, document_id, extraction.form_type, extraction.page),
            )
            for name, field in extraction.fields.items():
                connection.execute(
                    """INSERT INTO fields
                    (form_id, name, value_json, raw, page, bbox_json, source, confidence,
                     state, signals_json, handwritten, corrected_by_user)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        form_id,
                        name,
                        json.dumps(field.value, ensure_ascii=False) if field.value is not None else None,
                        field.raw,
                        field.page,
                        json.dumps(field.bbox) if field.bbox else None,
                        field.source,
                        field.confidence,
                        field.state,
                        json.dumps(field.signals),
                        int(field.handwritten),
                        int(field.corrected_by_user),
                    ),
                )
    return batch_id, document_id


def save_document_error(batch_id: str, filename: str, detail: str) -> None:
    with _connect() as connection:
        connection.execute(
            """INSERT INTO documents
            (id, batch_id, filename, status, error, created_at)
            VALUES (?, ?, ?, 'failed', ?, ?)""",
            (
                str(uuid.uuid4()),
                batch_id,
                filename,
                detail,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def read_batch(batch_id: str) -> dict | None:
    with _connect() as connection:
        batch = connection.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if batch is None:
            return None
        documents = connection.execute(
            "SELECT id, filename, status, error, approved FROM documents WHERE batch_id = ? ORDER BY created_at",
            (batch_id,),
        ).fetchall()
        output = []
        for document in documents:
            forms = connection.execute(
                "SELECT id, form_type, page, approved FROM forms WHERE document_id = ? ORDER BY page",
                (document["id"],),
            ).fetchall()
            form_list = []
            for form in forms:
                fields = connection.execute(
                    "SELECT * FROM fields WHERE form_id = ? ORDER BY name", (form["id"],)
                ).fetchall()
                form_list.append(
                    {
                        "id": form["id"],
                        "form_type": form["form_type"],
                        "page": form["page"],
                        "approved": bool(form["approved"]),
                        "fields": [_field_row(field) for field in fields],
                    }
                )
            output.append(
                {
                    "id": document["id"],
                    "filename": document["filename"],
                    "status": document["status"],
                    "error": document["error"],
                    "approved": bool(document["approved"]),
                    "forms": form_list,
                }
            )
        return {
            "id": batch["id"],
            "created_at": batch["created_at"],
            "status": batch["status"],
            "stage": batch["stage"],
            "documents": output,
        }


def _field_row(row: sqlite3.Row) -> dict:
    return {
        "name": row["name"],
        "value": json.loads(row["value_json"]) if row["value_json"] else None,
        "raw": row["raw"],
        "page": row["page"],
        "bbox": json.loads(row["bbox_json"]) if row["bbox_json"] else None,
        "source": row["source"],
        "confidence": row["confidence"],
        "state": row["state"],
        "needs_review": row["state"] != "green",
        "signals": json.loads(row["signals_json"]),
        "handwritten": bool(row["handwritten"]),
        "corrected_by_user": bool(row["corrected_by_user"]),
    }


def correct_field(
    document_id: str, field_name: str, value: str | list[str] | None, page: int = 1
) -> bool:
    with _connect() as connection:
        row = connection.execute(
            """SELECT fields.form_id, forms.form_type FROM fields
            JOIN forms ON forms.id = fields.form_id
            WHERE forms.document_id = ? AND forms.page = ? AND fields.name = ?""",
            (document_id, page, field_name),
        ).fetchone()
        if row is None:
            return False
        health_fund_row = connection.execute(
            "SELECT value_json FROM fields WHERE form_id = ? AND name = 'health_fund'",
            (row["form_id"],),
        ).fetchone()
        health_fund = (
            json.loads(health_fund_row["value_json"])
            if health_fund_row is not None and health_fund_row["value_json"]
            else None
        )
        if isinstance(health_fund, list):
            health_fund = health_fund[0] if health_fund else None
        state, confidence, signals = validate_user_value(
            field_name,
            value,
            row["form_type"],
            health_fund,
        )
        connection.execute(
            """UPDATE fields SET value_json = ?, state = ?, confidence = ?,
            signals_json = ?, source = 'user', corrected_by_user = 1
            WHERE form_id = ? AND name = ?""",
            (
                json.dumps(value, ensure_ascii=False) if value is not None else None,
                state,
                confidence,
                json.dumps(signals),
                row["form_id"],
                field_name,
            ),
        )
        connection.execute(
            "UPDATE forms SET approved = 0 WHERE id = ?", (row["form_id"],)
        )
        connection.execute("UPDATE documents SET approved = 0 WHERE id = ?", (document_id,))
        return True


def review_field(document_id: str, field_name: str, page: int = 1) -> bool:
    with _connect() as connection:
        row = connection.execute(
            """SELECT fields.form_id FROM fields JOIN forms ON forms.id = fields.form_id
            WHERE forms.document_id = ? AND forms.page = ? AND fields.name = ?""",
            (document_id, page, field_name),
        ).fetchone()
        if row is None:
            return False
        connection.execute(
            """UPDATE fields SET state = 'green', confidence = 1.0, source = 'user',
            corrected_by_user = 1 WHERE form_id = ? AND name = ?""",
            (row["form_id"], field_name),
        )
        connection.execute(
            "UPDATE forms SET approved = 0 WHERE id = ?", (row["form_id"],)
        )
        connection.execute("UPDATE documents SET approved = 0 WHERE id = ?", (document_id,))
        return True


def delete_document_form(document_id: str, page: int) -> bool:
    with _connect() as connection:
        form = connection.execute(
            "SELECT id FROM forms WHERE document_id = ? AND page = ?",
            (document_id, page),
        ).fetchone()
        if form is None:
            return False
        connection.execute("DELETE FROM forms WHERE id = ?", (form["id"],))
        remaining = connection.execute(
            "SELECT COUNT(*) AS count FROM forms WHERE document_id = ?", (document_id,)
        ).fetchone()["count"]
        if remaining == 0:
            connection.execute("DELETE FROM documents WHERE id = ?", (document_id,))
        else:
            unapproved = connection.execute(
                "SELECT COUNT(*) AS count FROM forms WHERE document_id = ? AND approved = 0",
                (document_id,),
            ).fetchone()["count"]
            connection.execute(
                "UPDATE documents SET approved = ? WHERE id = ?",
                (int(unapproved == 0), document_id),
            )
        return True


def approve_document(document_id: str, page: int | None = None) -> tuple[bool, str | None]:
    with _connect() as connection:
        document = connection.execute(
            "SELECT id FROM documents WHERE id = ?", (document_id,)
        ).fetchone()
        if document is None:
            return False, "not_found"
        page_filter = "AND forms.page = ?" if page is not None else ""
        parameters = (document_id, page) if page is not None else (document_id,)
        pending = connection.execute(
            f"""SELECT COUNT(*) AS count FROM fields
            JOIN forms ON forms.id = fields.form_id
            WHERE forms.document_id = ? {page_filter} AND fields.state != 'green'""",
            parameters,
        ).fetchone()["count"]
        if pending:
            return False, "review_required"
        if page is None:
            connection.execute(
                "UPDATE forms SET approved = 1 WHERE document_id = ?", (document_id,)
            )
        else:
            connection.execute(
                "UPDATE forms SET approved = 1 WHERE document_id = ? AND page = ?",
                (document_id, page),
            )
        remaining = connection.execute(
            "SELECT COUNT(*) AS count FROM forms WHERE document_id = ? AND approved = 0",
            (document_id,),
        ).fetchone()["count"]
        connection.execute(
            "UPDATE documents SET approved = ? WHERE id = ?",
            (int(remaining == 0), document_id),
        )
        return True, None


def approved_rows(document_ids: list[str] | None = None) -> list[dict]:
    if document_ids == []:
        return []
    with _connect() as connection:
        filter_sql = ""
        parameters: tuple = ()
        if document_ids is not None:
            placeholders = ", ".join("?" for _ in document_ids)
            filter_sql = f"AND documents.id IN ({placeholders})"
            parameters = tuple(document_ids)
        forms = connection.execute(
            """SELECT forms.id AS form_id, forms.form_type, forms.page, documents.filename
            FROM forms JOIN documents ON documents.id = forms.document_id
            WHERE (documents.approved = 1 OR forms.approved = 1)
            """
            + filter_sql
            + " ORDER BY documents.created_at, forms.page",
            parameters,
        ).fetchall()
        results = []
        for form in forms:
            fields = connection.execute(
                "SELECT name, value_json FROM fields WHERE form_id = ?", (form["form_id"],)
            ).fetchall()
            results.append(
                {
                    "filename": form["filename"],
                    "form_type": form["form_type"],
                    "page": form["page"],
                    **{
                        field["name"]: json.loads(field["value_json"]) if field["value_json"] else ""
                        for field in fields
                    },
                }
            )
        return results


def list_records(
    *,
    search: str | None = None,
    status: str | None = None,
    approved: bool | None = None,
    sender: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    search_text = (search or "").casefold().strip()
    sender_text = (sender or "").casefold().strip()
    with _connect() as connection:
        filters = []
        parameters: list = []
        if status:
            filters.append("documents.status = ?")
            parameters.append(status)
        if approved is not None:
            filters.append("forms.approved = ?")
            parameters.append(int(approved))
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        rows = connection.execute(
            f"""SELECT forms.id AS form_id, forms.document_id, forms.form_type,
                       forms.page, forms.approved, documents.filename, documents.status,
                       documents.error, documents.created_at, documents.batch_id
                FROM forms JOIN documents ON documents.id = forms.document_id
                {where}
                ORDER BY documents.created_at DESC, forms.page
                """,
            parameters,
        ).fetchall()
        records = []
        for row in rows:
            fields = connection.execute(
                "SELECT * FROM fields WHERE form_id = ? ORDER BY name", (row["form_id"],)
            ).fetchall()
            field_values = [_field_row(field) for field in fields]
            sender_field = next(
                (field["value"] for field in field_values if field["name"] == "sender"),
                None,
            )
            searchable = " ".join(
                [row["filename"], row["form_type"]]
                + [
                    str(field["value"] or "")
                    for field in field_values
                ]
            ).casefold()
            if search_text and search_text not in searchable:
                continue
            sender_value = str(sender_field or "").casefold().strip()
            if sender_text and sender_value != sender_text:
                continue
            records.append(
                {
                    "id": row["form_id"],
                    "document_id": row["document_id"],
                    "batch_id": row["batch_id"],
                    "filename": row["filename"],
                    "status": row["status"],
                    "error": row["error"],
                    "form_type": row["form_type"],
                    "page": row["page"],
                    "approved": bool(row["approved"]),
                    "created_at": row["created_at"],
                    "fields": field_values,
                }
            )
        return {
            "records": records[offset : offset + limit],
            "total": len(records),
            "limit": limit,
            "offset": offset,
        }


if SUPABASE_ENABLED:
    from app.services.supabase_store import (
        approve_document,
        approved_rows,
        correct_field,
        create_batch,
        delete_document_form,
        initialize_database,
        list_records,
        read_batch,
        review_field,
        save_document_error,
        save_extraction,
        update_batch_progress,
        update_batch_status,
        update_batch_progress,
    )
