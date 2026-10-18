from dataclasses import dataclass
from pathlib import Path

import fitz

from app.config import (
    ALLOWED_EXTENSIONS,
    MAX_DOCUMENT_PAGES,
    MAX_RENDER_PIXELS,
    MAX_UPLOAD_BYTES,
)


class InvalidDocumentError(ValueError):
    pass


@dataclass(frozen=True)
class PageImage:
    number: int
    png: bytes
    width: int
    height: int


def render_document(filename: str, content: bytes) -> list[PageImage]:
    extension = Path(filename).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise InvalidDocumentError("סוג הקובץ אינו נתמך. יש להעלות PDF, PNG או JPG.")
    if not content:
        raise InvalidDocumentError("הקובץ שהועלה ריק.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise InvalidDocumentError("הקובץ חורג ממגבלת 20MB.")

    filetype = "pdf" if extension == ".pdf" else "jpeg" if extension in {".jpg", ".jpeg"} else "png"
    try:
        document = fitz.open(stream=content, filetype=filetype)
        if document.needs_pass:
            document.close()
            raise InvalidDocumentError("לא ניתן לעבד PDF המוגן בסיסמה.")
        if document.page_count == 0:
            document.close()
            raise InvalidDocumentError("המסמך אינו מכיל עמודים.")
        if document.page_count > MAX_DOCUMENT_PAGES:
            document.close()
            raise InvalidDocumentError("המסמך מכיל יותר מ־100 עמודים.")

        pages = []
        for index, page in enumerate(document):
            scale = 300 / 72 if extension == ".pdf" else 1
            if page.rect.width * scale * page.rect.height * scale > MAX_RENDER_PIXELS:
                document.close()
                raise InvalidDocumentError("עמוד במסמך גדול מדי לעיבוד בטוח.")
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            pages.append(PageImage(index + 1, pixmap.tobytes("png"), pixmap.width, pixmap.height))
        document.close()
        return pages
    except InvalidDocumentError:
        raise
    except (fitz.FileDataError, RuntimeError, ValueError) as error:
        raise InvalidDocumentError("הקובץ פגום או שאינו תואם לסוג הקובץ.") from error
