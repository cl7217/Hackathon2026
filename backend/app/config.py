import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("EXTRACTION_DATA_DIR", str(BASE_DIR / "data"))).resolve()
DATABASE_PATH = DATA_DIR / "extractions.sqlite3"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_BATCH_BYTES = 100 * 1024 * 1024
MAX_BATCH_FILES = 50
MAX_DOCUMENT_PAGES = 100
MAX_RENDER_PIXELS = 24_000_000
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
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

EXTRACTION_MODE = os.getenv(
    "EXTRACTION_MODE",
    "hybrid",
).strip().casefold()
if EXTRACTION_MODE not in {"local_ocr_rules", "gemini", "hybrid"}:
    raise ValueError(
        "EXTRACTION_MODE must be local_ocr_rules, gemini, or hybrid."
    )
TESSERACT_COMMAND = os.getenv("TESSERACT_COMMAND", "tesseract")
OCR_LANGUAGES = os.getenv("OCR_LANGUAGES", "heb+eng")
SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ENABLED = bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY)

SENDER_ALLOWLIST = (
    "כללית",
    "מכבי",
    "מאוחדת",
    "לאומית",
    "יוספטל",
    "ברזילי",
    "אסף הרופא",
    "סורוקה",
    "אסותא באר שבע",
    "מעייני הישועה",
    "מ.ר.ב מרכז רפואי",
    "מרכז רפואי הרצליה",
    "הלל יפה",
    "וולפסון",
    "רמב״ם",
    "בני ציון",
    "הכרמל",
    "האיטלקי",
    "אלישע",
    "מרכז רפואי חורב",
    "אסותא חיפה",
    "פוריה",
    "הדסה עין כרם",
    "הדסה הר הצופים",
    "שערי צדק",
    "אל מקאסד",
    " ויקטוריה",
    "שערי צדק - ביקור חולים",
    "הסהר האדום",
    "בי״ח אלקודס ליולדות",
    "מאיר",
    "סנט ג'וזף",
    "נהריה",
    "הסקוטי",
    "סנט וינסנט",
    "המשפחה הקדושה",
    "לניאדו",
    "המרכזי בעמק",
    "רבין ק.בלינסון",
    "השרון - ק. גולדה",
    "זיו צפת",
    "אסותא ראשון לציון",
    "קפלן",
    "שיבא",
    "סנט ג'והן",
    "אסותא רמת החייל",
    "סוראסקי",
    "מרכז שניידר לילדים",
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT_SECONDS = int(
    os.getenv("GEMINI_TIMEOUT_SECONDS", "90")
)
