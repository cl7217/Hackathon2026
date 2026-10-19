from collections import OrderedDict
from threading import Lock

from app.pipeline.ingest import PageImage

_MAX_CACHE_BYTES = 64 * 1024 * 1024
_pages: OrderedDict[tuple[str, int], bytes] = OrderedDict()
_cache_size = 0
_lock = Lock()


def cache_document_pages(document_id: str, pages: list[PageImage]) -> None:
    global _cache_size
    with _lock:
        for page in pages:
            key = (document_id, page.number)
            existing = _pages.pop(key, None)
            if existing:
                _cache_size -= len(existing)
            _pages[key] = page.png
            _cache_size += len(page.png)
        while _cache_size > _MAX_CACHE_BYTES and _pages:
            _, removed = _pages.popitem(last=False)
            _cache_size -= len(removed)


def get_document_page(document_id: str, page: int) -> bytes | None:
    with _lock:
        key = (document_id, page)
        image = _pages.get(key)
        if image is not None:
            _pages.move_to_end(key)
        return image
