import json
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from app.config import DATA_DIR

AUDIT_LOG_PATH = DATA_DIR / "logs" / "extraction-events.jsonl"
_MAX_LOG_BYTES = 10 * 1024 * 1024
_BACKUP_COUNT = 5
_LOCK = RLock()
_PRIVATE_DETAIL_KEYS = {
    "content",
    "filename",
    "image",
    "ocr_text",
    "path",
    "prompt",
    "raw",
    "response",
    "text",
    "value",
}


def _validate_details(details: dict[str, Any]) -> None:
    pending: list[Any] = [details]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            forbidden = _PRIVATE_DETAIL_KEYS.intersection(value)
            if forbidden:
                raise ValueError(
                    "Audit details must not contain document or extracted content."
                )
            pending.extend(value.values())
        elif isinstance(value, (list, tuple)):
            pending.extend(value)


def _rotate_if_needed(incoming_size: int) -> None:
    if not AUDIT_LOG_PATH.exists():
        return
    if AUDIT_LOG_PATH.stat().st_size + incoming_size <= _MAX_LOG_BYTES:
        return

    oldest = AUDIT_LOG_PATH.with_name(f"{AUDIT_LOG_PATH.name}.{_BACKUP_COUNT}")
    oldest.unlink(missing_ok=True)
    for index in range(_BACKUP_COUNT - 1, 0, -1):
        source = AUDIT_LOG_PATH.with_name(f"{AUDIT_LOG_PATH.name}.{index}")
        if source.exists():
            source.replace(
                AUDIT_LOG_PATH.with_name(f"{AUDIT_LOG_PATH.name}.{index + 1}")
            )
    AUDIT_LOG_PATH.replace(AUDIT_LOG_PATH.with_name(f"{AUDIT_LOG_PATH.name}.1"))


def record_event(
    event: str,
    *,
    function: str,
    trace_id: str | None = None,
    batch_id: str | None = None,
    document_id: str | None = None,
    page: int | None = None,
    status: str = "info",
    duration_ms: int | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    safe_details = details or {}
    _validate_details(safe_details)
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "function": function,
        "trace_id": trace_id,
        "batch_id": batch_id,
        "document_id": document_id,
        "page": page,
        "status": status,
        "duration_ms": duration_ms,
        "details": safe_details,
    }
    line = (json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )

    with _LOCK:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        _rotate_if_needed(len(line))
        with AUDIT_LOG_PATH.open("ab") as log_file:
            log_file.write(line)
            log_file.flush()


def read_events(
    *,
    limit: int = 200,
    batch_id: str | None = None,
    trace_id: str | None = None,
    document_id: str | None = None,
) -> list[dict[str, Any]]:
    paths = [AUDIT_LOG_PATH]
    paths.extend(
        AUDIT_LOG_PATH.with_name(f"{AUDIT_LOG_PATH.name}.{index}")
        for index in range(1, _BACKUP_COUNT + 1)
    )
    events = []
    for path in paths:
        if not path.exists():
            continue
        for line in reversed(path.read_bytes().splitlines()):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise RuntimeError("The audit log contains an invalid JSON record.") from error
            if batch_id is not None and record.get("batch_id") != batch_id:
                continue
            if trace_id is not None and record.get("trace_id") != trace_id:
                continue
            if document_id is not None and record.get("document_id") != document_id:
                continue
            events.append(record)
            if len(events) >= limit:
                return list(reversed(events))
    return list(reversed(events))


def audit_log_path() -> Path:
    return AUDIT_LOG_PATH
