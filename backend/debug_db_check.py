from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import app.services.database as database
from app.schemas.extraction import ExtractedField, FormExtraction

with TemporaryDirectory() as d:
    root = Path(d)
    database.DATA_DIR = root
    database.DATABASE_PATH = root / 'test.sqlite3'
    database.initialize_database()
    batch_id = database.create_batch()
    extraction = FormExtraction(
        form_type='clalit',
        page=1,
        fields={
            'first_name': ExtractedField(value='דנה', state='orange'),
            'id_number': ExtractedField(value='123456782', state='green', needs_review=False),
            'sender': ExtractedField(value='כללית', state='green', needs_review=False),
        },
    )
    _, document_id = database.save_extraction('sample.pdf', [extraction], batch_id)
    print('LIST', database.list_records(search='דנה', sender='כללית'))
    con = sqlite3.connect(database.DATABASE_PATH)
    print('BATCHES', con.execute('SELECT * FROM batches').fetchall())
    print('DOCUMENTS', con.execute('SELECT * FROM documents').fetchall())
    print('FORMS', con.execute('SELECT * FROM forms').fetchall())
    print('FIELDS', con.execute('SELECT * FROM fields').fetchall())
