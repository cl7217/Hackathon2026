import unittest
import sys
from types import ModuleType

try:
    import openpyxl
except ModuleNotFoundError:
    openpyxl_stub = ModuleType("openpyxl")
    openpyxl_stub.Workbook = object
    styles_stub = ModuleType("openpyxl.styles")
    styles_stub.Alignment = object
    styles_stub.Font = object
    styles_stub.PatternFill = object
    sys.modules["openpyxl"] = openpyxl_stub
    sys.modules["openpyxl.styles"] = styles_stub

from app.main import app


class DocumentApiTests(unittest.TestCase):
    def test_document_upload_history_and_bulk_edit_routes_exist(self):
        paths = app.openapi()["paths"]
        self.assertIn("/api/documents/upload", paths)
        self.assertIn("/api/documents/batch/{batch_id}", paths)
        self.assertIn("/api/documents/{document_id}/fields", paths)
        self.assertIn("/api/documents/{document_id}/pages/{page}/image", paths)
        self.assertIn("post", paths["/api/documents/upload"])
        self.assertIn("patch", paths["/api/documents/{document_id}/fields"])


if __name__ == "__main__":
    unittest.main()
