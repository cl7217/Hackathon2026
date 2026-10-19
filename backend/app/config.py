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

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5vl:7b")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
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
    "בית חולים",
    "הדסה",
    "שיבא",
    "איכילוב",
    "רמב״ם",
    "רמבם",
    "סורוקה",
    "בילינסון",
    "שערי צדק",
    "וולפסון",
    "קפלן",
    "אסף הרופא",
    "ברזילי",
    "הלל יפה",
    "זיו",
    "פוריה",
    "לניאדו",
    "מעייני הישועה",
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
GEMINI_TIMEOUT_SECONDS = int(
    os.getenv("GEMINI_TIMEOUT_SECONDS", "90")
)
