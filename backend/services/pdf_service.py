import os
import json
import fitz  # PyMuPDF
import pandas as pd
from google import genai
from google.genai import types
from app.config import API_KEY
from app.schemas.extraction import FormExtractionSchema

def process_pdf_and_extract(pdf_path: str, excel_output_path: str = "extracted_data.xlsx") -> dict:
    """
    מבצע המרה של ה־PDF לתמונה, שולח למודל לחילוץ נתונים, ושומר לקובץ Excel.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"הקובץ {pdf_path} לא נמצא.")

    # 1. המרת עמוד ראשון לתמונה
    doc = fitz.open(pdf_path)
    if len(doc) == 0:
        raise ValueError("קובץ ה־PDF ריק.")

    page = doc[0]
    pix = page.get_pixmap(dpi=300)
    image_filename = "temp_page_1.png"
    pix.save(image_filename)
    doc.close()

    try:
        # 2. שליחה למודל ה־AI
        client = genai.Client(api_key=API_KEY)
        image_file = client.files.upload(file=image_filename)

        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=[
                image_file,
                "חלץ את כל השדות הנדרשים מתוך טופס ההתחייבות הרפואי שבתמונה בדיוק לפי מבנה הנתונים שהוגדר."
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=FormExtractionSchema,
            ),
        )

        extracted_json_text = response.text
        data_dict = json.loads(extracted_json_text)

        # 3. שמירה ל־Excel
        df = pd.DataFrame([data_dict])
        df.to_excel(excel_output_path, index=False, engine='openpyxl')

        return data_dict

    finally:
        # ניקוי קובץ התמונה הזמני
        if os.path.exists(image_filename):
            os.remove(image_filename)