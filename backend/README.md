# Medical Document Extraction API

מערכת מודולרית ומוכנה לייצור (Production-Ready) המבוסسة על FastAPI ו־Google Gemini AI, המיועדת לחילוץ אוטומטי של נתונים מטפסי התחייבות רפואיים (PDF או תמונות) והמרתם למבנה נתונים מובנה (JSON).

## מבנה הפרויקט

```text
my_medical_project/
│
├── app/
│   ├── config.py         # הגדרות תצורה ומשתני סביבה
│   ├── main.py           # נקודת הכניסה לשרת ה־FastAPI
│   ├── schemas/          # סכימות Pydantic לוולידציית נתונים
│   │   └── extraction.py
│   ├── services/         # לוגיקה עסקית ואינטגרציה עם Gemini
│   └── routers/          # נתיבי ה־API של המערכת
│
├── .env                  # משתני סביבה (מפתחות API)
├── requirements.txt      # רשימת התלויות והספריות בפרויקט
└── README.md
