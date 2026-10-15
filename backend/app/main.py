import os
from fastapi import FastAPI, UploadFile, File, HTTPException
from app.services.pdf_service import process_pdf_and_extract

app = FastAPI(title="Medical Document Extraction API", version="1.0.0")

@app.get("/")
def read_root():
    return {"message": "מערכת חילוץ הנתונים פועלת בהצלחה"}


@app.post("/api/extract/")
async def extract_document_endpoint(file: UploadFile = File(...)):
    """
    מקבל קובץ PDF דרך ממשק ה־API ומחזיר את הנתונים המחולצים.
    """
    if not file.filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="יש להעלות קובץ PDF תקין בלבד.")

    temp_pdf_path = f"temp_{file.filename}"

    try:
        # שמירת הקובץ שהועלה באופן זמני
        contents = await file.read()
        with open(temp_pdf_path, "wb") as f:
            f.write(contents)

        # הפעלת השירות לחילוץ הנתונים
        extracted_data = process_pdf_and_extract(temp_pdf_path)

        return {
            "status": "success",
            "filename": file.filename,
            "data": extracted_data
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    finally:
        # ניקוי קובץ ה־PDF הזמני
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)