import base64
import json
import logging
import subprocess
import urllib.error
import urllib.request

from app.config import (
    OCR_LANGUAGES,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    OLLAMA_URL,
    TESSERACT_COMMAND,
)
from app.pipeline.extractor import ExtractionCandidate, ExtractorUnavailableError

logger = logging.getLogger(__name__)

FIELD_NAMES = (
    "first_name",
    "last_name",
    "id_number",
    "center_number",
    "document_date",
    "sender",
    "commitment_number",
    "health_fund",
    "received_stamp",
)

_FORM_GUIDANCE = {
    "clalit": "בטפסי כללית שים לב לסימון המרכז הרפואי ולמספר התחייבות.",
    "maccabi": "בטפסי מכבי מספר ההתחייבות עשוי להופיע באזור האישור.",
    "meuhedet": "בטפסי מאוחדת בדוק את שדות המפנה וההתחייבות.",
    "leumit": "בטפסי לאומית מספר ההתחייבות עשוי להיות מסומן גם בשם דגימה.",
    "hospital": "בטופס בית חולים שים לב לחותמות, למדבקות ולמספרי התחייבות.",
    "unknown": "סוג הטופס אינו ידוע; השתמש בפרשנות כללית וזהירה.",
}


def read_ocr(image: bytes) -> str:
    try:
        result = subprocess.run(
            [TESSERACT_COMMAND, "stdin", "stdout", "-l", OCR_LANGUAGES, "--psm", "6"],
            input=image,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.warning("Local Tesseract OCR is unavailable; fields will require manual review.")
        return ""
    if result.returncode != 0:
        logger.warning("Local Tesseract OCR failed with exit code %s.", result.returncode)
        return ""
    return result.stdout.decode("utf-8", errors="replace").strip()


class LocalExtractor:
    def extract(
        self,
        image: bytes,
        *,
        form_type: str,
        ocr_text: str,
        width: int,
        height: int,
    ) -> ExtractionCandidate:
        prompt = f"""נתח את טופס ההתחייבות הרפואי שבתמונה. קרא עברית מימין לשמאל, טקסט מודפס,
כתב יד בעברית, מדבקות מטופל וחותמות. אל תנחש: ערך חסר או לא קריא חייב להיות null.
סוג הטופס שסווג: {form_type}. גודל התמונה: {width}x{height} פיקסלים.
{_FORM_GUIDANCE.get(form_type, _FORM_GUIDANCE["unknown"])}
החזר JSON בלבד עם אובייקט בשם fields. המפתחות הנדרשים: {", ".join(FIELD_NAMES)}.
לכל שדה החזר אובייקט עם value (מחרוזת, רשימת מחרוזות במספרים מרובים, או null),
raw (הטקסט כפי שנקרא), bbox ([x1,y1,x2,y2] או null) ו-handwritten (true/false).
ה-bbox חייב להיות בפיקסלים של התמונה, ומקיף את הטקסט עצמו. מספר מרכזי ומספרי התחייבות
עשויים להופיע כמה פעמים, החזר את כולם כרשימה. עבור מספרי תעודת זהות ומספרים, העתק רק
ספרות שנראות בבירור. ציין handwritten=true אם הערך נכתב ביד, גם אם אינך בטוח בו."""
        request_body = json.dumps(
            {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [base64.b64encode(image).decode("ascii")],
                "format": "json",
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ExtractorUnavailableError(
                "לא ניתן להתחבר למודל הראייה המקומי. יש להפעיל Ollama ולהוריד את המודל המוגדר."
            ) from error

        if not isinstance(payload, dict):
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר תשובה לא תקינה.")
        response_text = payload.get("response")
        if not isinstance(response_text, str) or not response_text.strip():
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר תשובה ריקה.")
        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as error:
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר JSON לא תקין.") from error

        fields = parsed.get("fields")
        if not isinstance(fields, dict):
            raise ExtractorUnavailableError("תשובת המודל חסרה אובייקט fields תקין.")
        return ExtractionCandidate(
            fields={name: fields.get(name, {}) for name in FIELD_NAMES},
            raw_response=response_text,
        )
