from pydantic import BaseModel, Field

class FormExtractionSchema(BaseModel):
    first_name: str = Field(description="שם פרטי של המטופל")
    last_name: str = Field(description="שם משפחה של המטופל")
    id_number: str = Field(description="מספר תעודת זהות (9 ספרות)")
    center_number: str = Field(description="מספר מרכזי")
    document_date: str = Field(description="תאריך קבלת הדגימה או הפקת ההתחייבות")
    sender: str = Field(description="גורם שולח (קופה או גורם רפואי)")
    commitment_number: str = Field(description="מספר התחייבות / דרישה")