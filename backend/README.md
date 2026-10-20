# הוראות הפעלה — מערכת חילוץ טפסי התחייבות

ההוראות מיועדות ל-Windows ול-PowerShell. להרצת המערכת המקומית לא צריך חשבון Supabase או חיבור למודל חיצוני.

## דרישות מקדימות

- Python 3.11 ומעלה
- Node.js ו-npm
- Tesseract OCR עם חבילות השפה `heb` ו-`eng`

בדקו ש-Python ו-Node.js זמינים:

```powershell
python --version
node --version
npm --version
tesseract --version
```

אם `tesseract` לא מזוהה, התקינו אותו והוסיפו אותו ל-`PATH`. ודאו שחבילות `heb` ו-`eng` מותקנות. אם הפקודה מותקנת בשם או במיקום אחר, הגדירו `TESSERACT_COMMAND` בקובץ `backend\.env`.

## התקנה והפעלת ה-backend

פתחו חלון PowerShell בתיקיית הפרויקט:

```powershell
cd D:\Hackathon2026\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

אם PowerShell חוסם הפעלת סקריפטים, אפשר לדלג על הפעלת הסביבה ולהריץ את `python` ואת `uvicorn` ישירות דרך `.\.venv\Scripts\python.exe` ו-`.\.venv\Scripts\uvicorn.exe`.

כתובת ה-API היא `http://127.0.0.1:8001`. תיעוד ה-API האינטראקטיבי זמין בכתובת `http://127.0.0.1:8001/docs`.

## התקנה והפעלת ה-frontend

פתחו חלון PowerShell שני:

```powershell
cd D:\Hackathon2026\frontend
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

פתחו בדפדפן את `http://127.0.0.1:5173`. ה-frontend פונה כברירת מחדל ל-backend ב-`http://127.0.0.1:8001`.

אם ה-backend פועל בכתובת אחרת, צרו `frontend\.env.local` והגדירו למשל:

```dotenv
VITE_API_URL=http://127.0.0.1:8001
```

לאחר שינוי משתני frontend יש להפעיל מחדש את שרת Vite.

## הגדרות ואחסון

ברירת המחדל ב-`backend\.env.example` היא:

```dotenv
EXTRACTION_MODE=hybrid
OCR_LANGUAGES=heb+eng
```

העתיקו את הקובץ ל-`backend\.env` לפני הפעלה. במצב ברירת המחדל, המערכת מנסה OCR מקומי ו-Gemini יחד, אך אם Gemini אינו זמין או נכשל, היא ממשיכה עם OCR מקומי במקום להפסיק.

ללא פרטי Supabase, הנתונים נשמרים ב-SQLite בתיקיית `backend\data`; תמונות התצוגה נשמרות בזיכרון בלבד. כדי לשנות את מיקום נתוני SQLite והיומן, אפשר להגדיר ב-`backend\.env`:

```dotenv
EXTRACTION_DATA_DIR=D:\MedicalExtractionData
```

### Supabase (אופציונלי)

1. צרו פרויקט Supabase.
2. הריצו את קובץ המיגרציה `backend\supabase\migrations\20261018000000_create_extraction_schema.sql` ב-SQL Editor של הפרויקט.
3. הגדירו ב-`backend\.env` את `SUPABASE_URL` ואת `SUPABASE_SERVICE_ROLE_KEY`.
4. הפעילו מחדש את ה-backend.

מפתח `service_role` הוא סודי: שומרים אותו רק ב-`backend\.env`, ולא בקובצי frontend, ב-Git או בהודעות. אין להשתמש במערכת עם מידע רפואי אמיתי לפני הוספת אימות והרשאות מתאימות.

## הרצה ובדיקות

בדיקות backend — מתוך `backend` כשהסביבה הווירטואלית פעילה:

```powershell
python -m compileall -q app tests
python -m unittest discover -s tests
```

בדיקת בניית frontend — מתוך `frontend`:

```powershell
npm run build
```

## העלאה, יומן וייצוא

- מעלים PDF, PNG או JPG דרך הממשק; ניתן לבחור עד 50 קבצים באצווה. מגבלת קובץ היא 20MB ומגבלת אצווה היא 100MB.
- מאשרים או מתקנים את הנתונים בממשק לפני ייצוא.
- יומן האירועים נמצא כברירת מחדל ב-`backend\data\logs\extraction-events.jsonl`.
- קריאת היומן זמינה ב-`http://127.0.0.1:8001/api/logs`; אפשר לסנן באמצעות `batch_id`, `trace_id` או `document_id`.
- ייצוא Excel זמין מתוך הממשק לאחר האישור.