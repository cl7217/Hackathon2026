import re
from app.pipeline.confidence import COMMITMENT_PREFIXES
from app.pipeline.normalize import is_valid_israeli_id, normalize_date


def extract_with_rules(ocr_text: str, form_type: str) -> dict[str, dict]:
    """
    חילוץ נתונים מהיר מבוסס כללים (RegEx / Pattern Matching) מטקסט ה-OCR.
    מחזיר מילון במבנה תואם ל-Extractor.
    """
    fields: dict[str, dict] = {}
    lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    full_text_clean = " ".join(lines)

    # 1. חילוץ תעודת זהות ישראלית (תקינה לפי ספרת ביקורת)
    id_matches = re.findall(r"\b\d{8,9}\b", full_text_clean)
    for cand in id_matches:
        cand_zfill = cand.zfill(9)
        if is_valid_israeli_id(cand_zfill):
            fields["id_number"] = {
                "value": cand_zfill,
                "raw": cand,
                "bbox": None,
                "handwritten": False,
            }
            break

    # 2. חילוץ מספר התחייבות (לפי תחילית קופת חולים)
    prefix = COMMITMENT_PREFIXES.get(form_type.lower())
    if prefix:
        commitments = re.findall(rf"\b{prefix}\d{{6,10}}\b", full_text_clean)
        if commitments:
            fields["commitment_number"] = {
                "value": commitments if len(commitments) > 1 else commitments[0],
                "raw": ", ".join(commitments),
                "bbox": None,
                "handwritten": False,
            }

    # 3. חילוץ תאריכים (תאריך קבלת הדגימה / הנפקה)
    date_matches = re.findall(r"\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b", full_text_clean)
    if date_matches:
        # בודקים תאריכים תקינים
        valid_dates = []
        for d in date_matches:
            norm, ok = normalize_date(d)
            if ok:
                valid_dates.append(norm)
        if valid_dates:
            fields["document_date"] = {
                "value": valid_dates[0],
                "raw": date_matches[0],
                "bbox": None,
                "handwritten": False,
            }

    # 4. זיהוי קופת חולים
    for fund_key, name_he in [("clalit", "כללית"), ("maccabi", "מכבי"), ("meuhedet", "מאוחדת"), ("leumit", "לאומית")]:
        if fund_key in form_type.lower() or name_he in full_text_clean:
            fields["health_fund"] = {
                "value": name_he,
                "raw": name_he,
                "bbox": None,
                "handwritten": False,
            }
            break

    return fields