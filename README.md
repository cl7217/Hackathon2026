# Medical Document Extraction System

מערכת מלאה (Full-Stack) לחילוץ אוטומטי של נתונים מטפסי התחייבות רפואיים, המבוססת על צד שרת מתקדם ב־FastAPI יחד עם בינה מלאכותית (Google Gemini), וממשק משתמש נקי ומודרני ב־React.

## מבנה הפרויקט

```text
my_medical_project/
│
├── app/                  # צד השרת (FastAPI)
│   ├── config.py         # הגדרות תצורה ומשתני סביבה
│   ├── main.py           # נקודת הכניסה הראשית לשרת
│   ├── schemas/          # סכימות Pydantic לוולידציית נתונים
│   │   └── extraction.py
│   └── routers/          # נתיבי ה־API של המערכת
│
├── frontend/             # צד הלקוח (React + Vite + Tailwind CSS)
│   ├── src/
│   │   ├── App.jsx       # רכיב ממשק המשתמש המרכזי
│   │   └── ...
│   └── package.json      # תלויות צד הלקוח
│
├── requirements.txt      # תלויות צד השרת
└── README.md             # תיעוד והוראות הפעלה למערכת
