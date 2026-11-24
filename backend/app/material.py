"""Durable background generation of clearly identified synthetic study material."""
import hashlib
import os
import secrets
import re
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .ai import generate
from .db import db, UPLOADS
from . import ingestion

executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='material')

def create(topic_id, description, name=None):
    with db() as c:
        if not c.execute('SELECT 1 FROM topics WHERE id=?', (topic_id,)).fetchone():
            return None
        job_id = c.execute('INSERT INTO material_generations(topic_id,description,requested_name) VALUES(?,?,?)', (topic_id,description,name)).lastrowid
    executor.submit(_run, job_id)
    return job_id

def retry(job_id):
    with db() as c:
        changed = c.execute("UPDATE material_generations SET status='queued',error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='failed'", (job_id,)).rowcount
    if changed:
        executor.submit(_run,job_id)
    return bool(changed)

def recover():
    with db() as c:
        c.execute("UPDATE material_generations SET status='queued' WHERE status='running'")
        jobs = [row[0] for row in c.execute("SELECT id FROM material_generations WHERE status='queued' ORDER BY id")]
    for job_id in jobs:
        executor.submit(_run,job_id)

def _run(job_id):
    final = None
    try:
        with db() as c:
            if not c.execute("UPDATE material_generations SET status='running',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='queued'",(job_id,)).rowcount:
                return
            job = c.execute('SELECT g.*,t.name topic_name,c.name course_name FROM material_generations g JOIN topics t ON t.id=g.topic_id JOIN courses c ON c.id=t.course_id WHERE g.id=?',(job_id,)).fetchone()
            if not job:
                return
            job = dict(job)
        prompt = ("Create a compact, factual reference for generating retrieval-practice questions about the requested subject. "
                  "This is a reference for writing standalone questions, not a lesson or copy of the request. "
                  "Extract and explain the general domain concepts rather than repeating an assignment, task instructions, "
                  "specific file names, commands, evaluation requirements, or descriptions of an exercise. "
                  "Use terse bullet points, typically 100–250 words for a single subject, "
                  "with key definitions, distinctions, formulas, constraints and only essential context. Avoid long explanations, "
                  "introductions, repeated points, exercises, invented references, disclaimers, or mentions of AI generation. "
                  "Do not invent citations, claim access to a syllabus, or imply these notes were supplied by the user. "
                  "If the description is ambiguous, state the assumptions. Return JSON with one nonempty string field "
                  "named 'material' containing Markdown notes and a 'focus' object with 'scope' ('single' or 'multiple') "
                  "and 'name' (the concise subject name). A single named subject such as 'bloom filters' is one "
                  "subject, regardless of its properties, formulas, variations, or applications. Use 'multiple' "
                  "only for a description requesting several distinct subjects. Course and topic names are context; the description "
                  "is the learning request.\nCourse: " + job['course_name'] + "\nTopic: " + job['topic_name'] +
                  "\nLearning request:\n" + job['description'])
        description_words = ' '.join(re.findall(r'\w+', job['description'].casefold()))
        for attempt in range(2):
            result = generate(prompt + ('\nDo not copy or paraphrase the request as the reference. Provide domain facts.' if attempt else ''))
            notes = result.get('material')
            if not isinstance(notes,str) or not notes.strip():
                continue
            note_words = ' '.join(re.findall(r'\w+',notes.casefold()))
            if not note_words or note_words in description_words or SequenceMatcher(None,description_words,note_words,autojunk=False).ratio() > .85:
                continue
            break
        else:
            raise ValueError('The AI did not return distinct reference material. Please retry.')
        focus = result.get('focus')
        scope = focus.get('scope') if isinstance(focus,dict) else None
        focus_name = focus.get('name') if isinstance(focus,dict) else None
        if scope not in ('single','multiple') or not isinstance(focus_name,str) or not focus_name.strip() or len(focus_name)>200:
            scope, focus_name = None, None
        else:
            focus_name = focus_name.strip()
        filename = job['requested_name'] or focus_name or job['description'].split('\n')[0][:80]
        filename = ' '.join(filename.replace('/',' ').replace('\\',' ').split()).strip('. ') or 'Study material'
        if filename.lower().endswith('.md'):
            filename = filename[:-3].strip('. ') or 'Study material'
        body = re.sub(r'^#\s+[^\n]+\n+', '', notes.strip(), count=1)
        content = ('# ' + filename + '\n\n' + body + '\n').encode('utf-8')
        digest = hashlib.sha256(content).hexdigest()
        key = secrets.token_hex(24)
        temp = Path(UPLOADS,key+'.tmp')
        final = Path(UPLOADS,key)
        try:
            temp.write_bytes(content)
            os.replace(temp,final)
            with db() as c:
                if not c.execute('SELECT 1 FROM material_generations WHERE id=?',(job_id,)).fetchone():
                    final.unlink(missing_ok=True)
                    return
                existing = c.execute('SELECT id FROM files WHERE topic_id=? AND sha256=?',(job['topic_id'],digest)).fetchone()
                if existing:
                    file_id = existing['id']
                    final.unlink(missing_ok=True)
                else:
                    file_id = c.execute('INSERT INTO files(topic_id,original_name,storage_key,sha256,mime_type,size_bytes) VALUES(?,?,?,?,?,?)',
                                        (job['topic_id'],f'{filename}.md',key,digest,'text/plain',len(content))).lastrowid
                c.execute("UPDATE material_generations SET status='complete',file_id=?,concept_scope=?,concept_name=?,error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",(file_id,scope,focus_name,job_id))
                c.execute("INSERT INTO ingestion_jobs(topic_id,status) VALUES(?,'queued')",(job['topic_id'],))
                c.execute("UPDATE topics SET index_status='queued',last_error=NULL WHERE id=?",(job['topic_id'],))
            final = None
            ingestion.schedule(job['topic_id'])
        finally:
            temp.unlink(missing_ok=True)
    except Exception:
        if final:
            final.unlink(missing_ok=True)
        with db() as c:
            c.execute("UPDATE material_generations SET status='failed',error='Could not generate material. Please retry.',updated_at=CURRENT_TIMESTAMP WHERE id=?",(job_id,))
