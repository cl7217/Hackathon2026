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

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "object",
            "properties": {
                name: {
                    "type": "object",
                    "properties": {
                        "value": {"type": ["string", "array", "null"], "items": {"type": "string"}},
                        "raw": {"type": ["string", "null"]},
                        "bbox": {"type": ["array", "null"], "items": {"type": "integer"}, "maxItems": 4, "minItems": 4},
                        "handwritten": {"type": "boolean"}
                    },
                    "required": ["value", "raw", "bbox", "handwritten"]
                }
                for name in FIELD_NAMES
            },
            "required": list(FIELD_NAMES)
        }
    },
    "required": ["fields"]
}

FIELD_CROP_SCHEMA = {
    "type": "object",
    "properties": {
        "value": {"type": ["string", "array", "null"], "items": {"type": "string"}},
        "raw": {"type": ["string", "null"]},
        "handwritten": {"type": "boolean"}
    },
    "required": ["value", "raw", "handwritten"]
}


def read_ocr(image: bytes) -> str:
    try:
        result = subprocess.run(
            [
                TESSERACT_COMMAND,
                "stdin",
                "stdout",
                "-l",
                OCR_LANGUAGES,
                "--psm",
                "6",
            ],
            input=image,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        logger.exception("Local Tesseract OCR is unavailable.")
        return ""

    if result.returncode != 0:
        logger.error(
            "Tesseract OCR failed. Exit code=%s, stderr=%s",
            result.returncode,
            result.stderr.decode("utf-8", errors="replace")[:2000],
        )
        return ""

    return result.stdout.decode("utf-8", errors="replace").strip()


class LocalExtractor:
    @staticmethod
    def crop_field_image(
            image: bytes,
            *,
            bbox: list[int],
            width: int,
            height: int,
    ) -> bytes:
        import fitz

        if (
                len(bbox) != 4
                or bbox[0] < 0
                or bbox[1] < 0
                or bbox[2] > width
                or bbox[3] > height
                or bbox[2] <= bbox[0]
                or bbox[3] <= bbox[1]
        ):
            raise ValueError("Invalid extraction bounding box.")

        with fitz.open(stream=image, filetype="png") as source:
            crop = source[0].get_pixmap(
                clip=fitz.Rect(*bbox),
                matrix=fitz.Matrix(2, 2),
                alpha=False,
            )

        return crop.tobytes("png")

    @staticmethod
    def downscale_for_vlm(image: bytes, max_dim: int = 1280) -> bytes:
        """הקטנת תמונה למודל הראייה כדי לחסוך טוקנים חזותיים בלבד"""
        import fitz
        with fitz.open(stream=image, filetype="png") as source:
            page = source[0]
            w, h = page.rect.width, page.rect.height
            if w > max_dim or h > max_dim:
                scale = min(max_dim / w, max_dim / h)
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                return pixmap.tobytes("png")
        return image

    def _generate(self, image: bytes, prompt: str, json_schema: dict | None = None) -> dict:
        body = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "images": [base64.b64encode(image).decode("ascii")],
            "stream": False,
            "options": {
                "num_ctx": 8192,  # הגדלת חלון ההקשר כדי למנוע שגיאות Exceeds Context Size
            }
        }

        if json_schema:
            body["format"] = json_schema
        else:
            body["format"] = "json"

        request_body = json.dumps(body).encode("utf-8")
        url = f"{OLLAMA_URL.rstrip('/')}/api/generate"

        request = urllib.request.Request(
            url,
            data=request_body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        logger.info(
            "Sending request to Ollama. URL=%s, model=%s, image_bytes=%d",
            url,
            OLLAMA_MODEL,
            len(image),
        )

        try:
            with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
                payload = json.loads(response.read())

        except urllib.error.HTTPError as error:
            error_body = error.read().decode("utf-8", errors="replace")[:4000]
            logger.error("Ollama HTTP error. Status=%s, body=%s", error.code, error_body)
            raise ExtractorUnavailableError(f"Ollama החזיר שגיאת HTTP {error.code}: {error_body}") from error

        except urllib.error.URLError as error:
            logger.exception("Cannot connect to Ollama.")
            raise ExtractorUnavailableError(f"לא ניתן להתחבר ל-Ollama בכתובת {url}: {error.reason}") from error

        except TimeoutError as error:
            logger.exception("Ollama request timed out.")
            raise ExtractorUnavailableError(f"Ollama לא השיב בתוך {OLLAMA_TIMEOUT_SECONDS} שניות.") from error

        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            logger.exception("Ollama returned an invalid JSON response.")
            raise ExtractorUnavailableError("Ollama החזיר תשובת JSON לא תקינה.") from error

        if not isinstance(payload, dict):
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר תשובה לא תקינה.")

        response_text = payload.get("response")

        if not isinstance(response_text, str) or not response_text.strip():
            logger.error("Ollama returned an empty response.")
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר תשובה ריקה.")

        try:
            parsed = json.loads(response_text)
        except json.JSONDecodeError as error:
            logger.error("Ollama returned invalid JSON content: %s", response_text[:2000])
            raise ExtractorUnavailableError("מודל הראייה המקומי החזיר JSON לא תקין.") from error

        if not isinstance(parsed, dict):
            raise ExtractorUnavailableError("תשובת מודל הראייה המקומי אינה אובייקט JSON.")

        return parsed

    def extract(
            self,
            image: bytes,
            *,
            form_type: str,
            ocr_text: str,
            width: int,
            height: int,
    ) -> ExtractionCandidate:
        vlm_image = self.downscale_for_vlm(image)
        trimmed_ocr = ocr_text[:1500] if ocr_text else ""

        prompt = f"""חלץ נתונים מטופס {form_type} ({width}x{height}). 
אל תנחש: ערך חסר או לא קריא חייב להיות null.
{_FORM_GUIDANCE.get(form_type, _FORM_GUIDANCE["unknown"])}
רמז טקסט OCR מקומי:
{trimmed_ocr}"""

        parsed = self._generate(vlm_image, prompt, json_schema=EXTRACTION_SCHEMA)

        fields = parsed.get("fields")
        if not isinstance(fields, dict):
            logger.error("Model response is missing a valid fields object.")
            raise ExtractorUnavailableError("תשובת המודל חסרה אובייקט fields תקין.")

        return ExtractionCandidate(
            fields={name: fields.get(name, {}) for name in FIELD_NAMES},
            raw_response=json.dumps(parsed, ensure_ascii=False),
        )

    def extract_field_crop(
            self,
            image: bytes,
            *,
            field_name: str,
            bbox: list[int],
            width: int,
            height: int,
    ) -> dict:
        crop = self.crop_field_image(
            image,
            bbox=bbox,
            width=width,
            height=height,
        )

        prompt = f"""תמונת חיתוך של השדה {field_name} מטופס רפואי.
קרא את הערך בדיוק כפי שמופיע. אל תנחש: אם אינו קריא או חסר, החזר null."""

        result = self._generate(crop, prompt, json_schema=FIELD_CROP_SCHEMA)

        if "value" not in result or (
                result["value"] is not None
                and not isinstance(result["value"], (str, list))
        ):
            logger.error("Invalid field crop response for field=%s", field_name)
            raise ExtractorUnavailableError("מודל הראייה החזיר ערך שדה בפורמט לא תקין.")

        return result