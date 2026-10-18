from typing import Literal

from pydantic import BaseModel, Field

FieldValue = str | list[str] | None


class ExtractedField(BaseModel):
    value: FieldValue = None
    page: int | None = None
    bbox: list[int] | None = None
    source: Literal["vlm", "ocr", "user"] = "vlm"
    raw: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    state: Literal["green", "orange", "empty"] = "empty"
    needs_review: bool = True
    signals: dict[str, bool] = Field(default_factory=dict)
    handwritten: bool = False
    corrected_by_user: bool = False


class FormExtraction(BaseModel):
    form_type: str
    page: int
    fields: dict[str, ExtractedField]

    def frontend_data(self) -> dict:
        field_values = {
            name: {
                **field.model_dump(mode="json"),
                "needs_review": field.needs_review,
            }
            for name, field in self.fields.items()
        }
        review_fields = [
            name for name, field in self.fields.items() if field.needs_review
        ]
        return {
            **field_values,
            "form_type": self.form_type,
            "page": self.page,
            "needs_review_fields": review_fields,
        }
