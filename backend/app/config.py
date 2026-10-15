import os
from dotenv import load_dotenv

# טעינת משתני סביבה מקובץ .env במידה וקיים
load_dotenv()

# קריאת מפתח הגישה ל־API מתוך משתנה סביבה לשמירה על אבטחת המידע
API_KEY = os.getenv("GEMINI_API_KEY")