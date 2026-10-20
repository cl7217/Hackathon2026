from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractionCandidate:
    fields: dict[str, dict]
    raw_response: str


class ExtractorUnavailableError(RuntimeError):
    pass


class Extractor(Protocol):
    def extract(
        self,
        image: bytes,
        *,
        form_type: str,
        ocr_text: str,
        width: int,
        height: int,
    ) -> ExtractionCandidate: ...

    def extract_field_crop(
        self,
        image: bytes,
        *,
        field_name: str,
        bbox: list[int],
        width: int,
        height: int,
    ) -> dict: ...
