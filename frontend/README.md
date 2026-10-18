# MedExtract frontend

The frontend accepts multiple PDF, PNG, and JPG forms (up to 20 MB each) and submits
them to the backend batch queue. Each PDF page is shown as a separate form row.
Fields flagged as uncertain by the extraction response, as well as empty fields, are
highlighted for review. Open a document to preview it, edit values, and mark uncertain
fields as checked before approving it.

Only approved documents are included in the `.xlsx` export. Extraction still uses the
configured API endpoint:

- `VITE_API_URL` sets the service base URL (defaults to `http://127.0.0.1:8000`).
- Extraction is submitted to the backend batch API at `/api/batches`; batch status is
  read from `/api/batches/{batch_id}`.

Run locally with `npm install` and `npm run dev`.
