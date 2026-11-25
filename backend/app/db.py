import os, sqlite3
from contextlib import contextmanager

DATA = os.getenv('DATA_DIR', '/data')
DB = os.path.join(DATA, 'study.db')
UPLOADS = os.path.join(DATA, 'uploads')
os.makedirs(UPLOADS, exist_ok=True)

@contextmanager
def db():
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA busy_timeout=30000')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

def init():
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
CREATE TABLE IF NOT EXISTS courses(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS topics(id INTEGER PRIMARY KEY, course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE, name TEXT NOT NULL, index_status TEXT NOT NULL DEFAULT 'empty', index_revision INTEGER NOT NULL DEFAULT 0, last_error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(course_id,name));
CREATE INDEX IF NOT EXISTS topics_course ON topics(course_id);
CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE, original_name TEXT NOT NULL, storage_key TEXT NOT NULL, sha256 TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending', error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(topic_id,sha256));
CREATE INDEX IF NOT EXISTS files_topic ON files(topic_id);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL, content TEXT NOT NULL, page_start INTEGER, page_end INTEGER, line_start INTEGER, line_end INTEGER, embedding BLOB NOT NULL, embedding_model TEXT NOT NULL, UNIQUE(file_id,ordinal));
CREATE INDEX IF NOT EXISTS chunks_file ON chunks(file_id);
CREATE TABLE IF NOT EXISTS subtopics(id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE, name TEXT NOT NULL, description TEXT NOT NULL, proficiency REAL NOT NULL DEFAULT 0.0 CHECK(proficiency BETWEEN 0 AND 1), active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS subtopics_topic ON subtopics(topic_id);
CREATE TABLE IF NOT EXISTS failed_cards(id INTEGER PRIMARY KEY, subtopic_id INTEGER NOT NULL REFERENCES subtopics(id) ON DELETE CASCADE, question_type TEXT NOT NULL, front TEXT NOT NULL, back TEXT NOT NULL, sources_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS failed_subtopic ON failed_cards(subtopic_id);
CREATE TABLE IF NOT EXISTS saved_cards(id INTEGER PRIMARY KEY, subtopic_id INTEGER NOT NULL REFERENCES subtopics(id) ON DELETE CASCADE, question_type TEXT NOT NULL, front TEXT NOT NULL, back TEXT NOT NULL, sources_json TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(subtopic_id,front,back));
CREATE INDEX IF NOT EXISTS saved_subtopic ON saved_cards(subtopic_id);
CREATE TABLE IF NOT EXISTS recent_grades(id INTEGER PRIMARY KEY AUTOINCREMENT, subtopic_id INTEGER NOT NULL REFERENCES subtopics(id) ON DELETE CASCADE, known INTEGER NOT NULL CHECK(known IN (0,1)));
CREATE INDEX IF NOT EXISTS recent_grades_subtopic ON recent_grades(subtopic_id,id);
CREATE TABLE IF NOT EXISTS ingestion_jobs(id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE, status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS jobs_topic ON ingestion_jobs(topic_id);
CREATE TABLE IF NOT EXISTS material_generations(id INTEGER PRIMARY KEY, topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE, description TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued', error TEXT, file_id INTEGER REFERENCES files(id) ON DELETE SET NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX IF NOT EXISTS generations_topic ON material_generations(topic_id);

''')
        subtopic_columns = {row['name'] for row in c.execute('PRAGMA table_info(subtopics)')}
        if 'graded_count' not in subtopic_columns:
            c.execute('ALTER TABLE subtopics ADD COLUMN graded_count INTEGER NOT NULL DEFAULT 0')
        columns = {row['name'] for row in c.execute('PRAGMA table_info(material_generations)')}
        if 'concept_scope' not in columns:
            c.execute('ALTER TABLE material_generations ADD COLUMN concept_scope TEXT')
        if 'concept_name' not in columns:
            c.execute('ALTER TABLE material_generations ADD COLUMN concept_name TEXT')
        if 'requested_name' not in columns:
            c.execute('ALTER TABLE material_generations ADD COLUMN requested_name TEXT')
