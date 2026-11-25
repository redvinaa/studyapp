import hashlib, json, os, secrets, time
from pathlib import Path
from urllib.parse import quote
from fastapi import FastAPI, Request, Response, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from argon2 import PasswordHasher
from itsdangerous import URLSafeTimedSerializer, BadSignature
from .db import db, init, UPLOADS
from . import ingestion, material, study
from .source_files import generated_filename, generated_reference

app=FastAPI()
secret=os.environ['SESSION_SECRET']; password_hash=os.environ['PASSWORD_HASH']
signer=URLSafeTimedSerializer(secret,salt='study-session'); ph=PasswordHasher(); attempts={}
MAX_BYTES=int(os.getenv('MAX_UPLOAD_MB','50'))*1024*1024

def error(code,message,status): return JSONResponse({'error':{'code':code,'message':message}},status_code=status)

@app.on_event('startup')
def startup(): init(); ingestion.recover(); material.recover(); study.prewarm()

@app.middleware('http')
async def protect(request:Request,call_next):
    path=request.url.path
    if path.startswith('/api/') and path!='/api/login':
        try: signer.loads(request.cookies.get('study_session',''),max_age=604800)
        except BadSignature: return error('unauthenticated','Please sign in.',401)
    if request.method in ('POST','PATCH','DELETE') and path.startswith('/api/'):
        origin=request.headers.get('origin'); host=request.headers.get('host')
        if origin and origin not in (f'https://{host}',f'http://{host}'): return error('invalid_origin','Invalid request origin.',403)
        if not origin and request.headers.get('sec-fetch-site') not in ('same-origin','none'): return error('invalid_origin','Request origin required.',403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.get('/health')
def health(): return {'status':'ok'}

@app.post('/api/login')
async def login(request:Request,response:Response):
    ip=request.client.host; now=time.monotonic(); recent=[x for x in attempts.get(ip,[]) if now-x<300]
    if len(recent)>=10: return error('rate_limited','Too many attempts. Try again later.',429)
    try: valid=ph.verify(password_hash,str((await request.json()).get('password','')))
    except Exception: valid=False
    if not valid:
        attempts[ip]=recent+[now]; return error('invalid_credentials','Incorrect password.',401)
    attempts.pop(ip,None)
    response.set_cookie('study_session',signer.dumps('authenticated'),httponly=True,secure=True,samesite='strict',max_age=604800)
    return {'ok':True}

@app.post('/api/logout')
def logout(response:Response): response.delete_cookie('study_session',secure=True,httponly=True,samesite='strict'); return {'ok':True}
@app.get('/api/me')
def me(): return {'authenticated':True}

@app.get('/api/tree')
def tree():
    with db() as c:
        saved_counts={r['subtopic_id']:r['n'] for r in c.execute('SELECT subtopic_id,COUNT(*) n FROM saved_cards GROUP BY subtopic_id')}
        grades={}
        for row in c.execute('SELECT id,subtopic_id,known FROM recent_grades ORDER BY id DESC'):
            grades.setdefault(row['subtopic_id'],[]).append((row['id'],bool(row['known'])))
        courses=[dict(r) for r in c.execute('SELECT * FROM courses ORDER BY name COLLATE NOCASE')]
        for course in courses:
            course['topics']=[dict(r) for r in c.execute('SELECT * FROM topics WHERE course_id=? ORDER BY name COLLATE NOCASE',(course['id'],))]
            values=[]
            for topic in course['topics']:
                topic['subtopics']=[dict(r) for r in c.execute('SELECT id,name,description,proficiency,graded_count FROM subtopics WHERE topic_id=? AND active=1 ORDER BY name COLLATE NOCASE',(topic['id'],))]
                for subtopic in topic['subtopics']:
                    subtopic['saved_count']=saved_counts.get(subtopic['id'],0)
                    subtopic['recent_answers']=[x[1] for x in grades.get(subtopic['id'],[])[:5]]
                topic['files']=[dict(r) for r in c.execute('SELECT f.id,f.original_name,f.size_bytes,f.status,f.error,(SELECT g.description FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS generated_description,(SELECT g.requested_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS requested_name,(SELECT g.concept_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS concept_name FROM files f WHERE f.topic_id=? ORDER BY f.id',(topic['id'],))]
                for file in topic['files']:
                    description=file.pop('generated_description')
                    requested=file.pop('requested_name'); concept=file.pop('concept_name')
                    if description: file['original_name']=generated_filename(file['original_name'],description,requested,concept)
                topic['generations']=[dict(r) for r in c.execute("SELECT id,status,error FROM material_generations WHERE topic_id=? AND status IN ('queued','running','failed') ORDER BY id",(topic['id'],))]
                vs=[s['proficiency'] for s in topic['subtopics']]; values.extend(vs)
                topic['saved_count']=sum(s['saved_count'] for s in topic['subtopics'])
                topic['graded_count']=sum(s['graded_count'] for s in topic['subtopics'])
                topic_grades=sorted((g for sub in topic['subtopics'] for g in grades.get(sub['id'],[])),reverse=True)
                topic['recent_answers']=[x[1] for x in topic_grades[:5]]
                topic['_grade_order']=topic_grades[:5]
                topic['proficiency']=sum(vs)/len(vs) if vs else None
            course['proficiency']=sum(values)/len(values) if values else None
            course['saved_count']=sum(t['saved_count'] for t in course['topics'])
            course['graded_count']=sum(t['graded_count'] for t in course['topics'])
            course_grades=sorted((g for t in course['topics'] for g in t.pop('_grade_order')),reverse=True)
            course['recent_answers']=[x[1] for x in course_grades[:5]]
        return courses

async def get_name(request):
    try: name=(await request.json()).get('name','').strip()
    except Exception: return None
    return name if 0<len(name)<=200 else None

@app.post('/api/courses')
@app.post('/api/courses/{course_id}/topics')
async def create(request:Request,course_id:int=None):
    import sqlite3
    name=await get_name(request)
    if not name: return error('invalid_name','Enter a name of up to 200 characters.',400)
    try:
        with db() as c:
            if course_id is None: cur=c.execute('INSERT INTO courses(name) VALUES(?)',(name,))
            else:
                if not c.execute('SELECT 1 FROM courses WHERE id=?',(course_id,)).fetchone(): return error('not_found','Course not found.',404)
                cur=c.execute('INSERT INTO topics(course_id,name) VALUES(?,?)',(course_id,name))
            return {'id':cur.lastrowid,'name':name}
    except sqlite3.IntegrityError: return error('conflict','That name already exists.',409)

@app.patch('/api/courses/{item_id}')
@app.patch('/api/topics/{item_id}')
async def rename(item_id:int,request:Request):
    import sqlite3
    name=await get_name(request)
    if not name: return error('invalid_name','Enter a name of up to 200 characters.',400)
    table='courses' if '/courses/' in request.url.path else 'topics'
    try:
        with db() as c:
            if not c.execute(f'UPDATE {table} SET name=? WHERE id=?',(name,item_id)).rowcount: return error('not_found','Item not found.',404)
        return {'ok':True}
    except sqlite3.IntegrityError: return error('conflict','That name already exists.',409)

@app.delete('/api/courses/{item_id}')
@app.delete('/api/topics/{item_id}')
def delete(item_id:int,request:Request):
    table='courses' if '/courses/' in request.url.path else 'topics'
    with db() as c:
        if table=='courses':
            topic_ids=[r[0] for r in c.execute('SELECT id FROM topics WHERE course_id=?',(item_id,))]
            files=c.execute('SELECT f.storage_key FROM files f JOIN topics t ON t.id=f.topic_id WHERE t.course_id=?',(item_id,)).fetchall()
        else:
            topic_ids=[item_id]
            files=c.execute('SELECT storage_key FROM files WHERE topic_id=?',(item_id,)).fetchall()
        if not c.execute(f'DELETE FROM {table} WHERE id=?',(item_id,)).rowcount: return error('not_found','Item not found.',404)
    study.invalidate_topics(topic_ids)
    for f in files: Path(UPLOADS,f['storage_key']).unlink(missing_ok=True)
    return {'ok':True}

@app.post('/api/topics/{topic_id}/files',status_code=202)
async def upload(topic_id:int,files:list[UploadFile]=File(...)):
    with db() as c:
        if not c.execute('SELECT 1 FROM topics WHERE id=?',(topic_id,)).fetchone(): return error('not_found','Topic not found.',404)
    added=[]
    for f in files:
        name=f.filename or ''
        if not name or '/' in name or '\\' in name or name in ('.','..'): return error('invalid_filename','Invalid file name.',422)
        ext=Path(name).suffix.lower()
        key=secrets.token_hex(24); temp=Path(UPLOADS,key+'.tmp'); final=Path(UPLOADS,key)
        size=0; digest=hashlib.sha256()
        try:
            with temp.open('wb') as out:
                while chunk:=await f.read(1024*1024):
                    size+=len(chunk)
                    if size>MAX_BYTES: return error('too_large','File exceeds the upload limit.',413)
                    digest.update(chunk); out.write(chunk)
            if size==0: return error('empty_file','The file is empty.',422)
            with temp.open('rb') as inp: prefix=inp.read(1024)
            if ext=='.pdf' and not prefix.startswith(b'%PDF-'): return error('invalid_content','This is not a valid PDF.',422)
            if ext!='.pdf':
                try:
                    text=temp.read_text(encoding='utf-8-sig')
                    if any(ord(ch)<32 and ch not in '\t\r\n\f' for ch in text): raise ValueError()
                    if ext=='.ipynb':
                        notebook=json.loads(text)
                        if not isinstance(notebook.get('cells'),list) or not all(isinstance(cell,dict) and (isinstance(cell.get('source',[]),str) or isinstance(cell.get('source',[]),list) and all(isinstance(line,str) for line in cell['source'])) for cell in notebook['cells']): raise ValueError()
                except (UnicodeError,ValueError,AttributeError): return error('invalid_content','Upload a UTF-8 text file or PDF.',422)
            with db() as c:
                existing=c.execute('SELECT id FROM files WHERE topic_id=? AND sha256=?',(topic_id,digest.hexdigest())).fetchone()
                if existing: added.append({'id':existing['id'],'duplicate':True}); continue
                os.replace(temp,final)
                try:
                    fid=c.execute('INSERT INTO files(topic_id,original_name,storage_key,sha256,mime_type,size_bytes) VALUES(?,?,?,?,?,?)',(topic_id,name,key,digest.hexdigest(),'application/pdf' if ext=='.pdf' else 'text/plain',size)).lastrowid
                except Exception:
                    final.unlink(missing_ok=True); raise
                added.append({'id':fid,'duplicate':False})
        finally: temp.unlink(missing_ok=True); await f.close()
    job=ingestion.enqueue(topic_id) if any(not x['duplicate'] for x in added) else None
    return {'files':added,'job_id':job}

@app.post('/api/topics/{topic_id}/generate-material',status_code=202)
async def generate_material(topic_id:int, request:Request):
    try:
        data=await request.json()
        description=data.get('description','')
        name=data.get('name')
        if not isinstance(description,str): raise ValueError()
        if name is not None:
            if not isinstance(name,str) or len(name.strip())>100 or any(x in name for x in ('/','\\','\x00')): raise ValueError()
            name=name.strip() or None
        description=description.strip()
        if not 10 <= len(description) <= 8000: raise ValueError()
    except (ValueError,TypeError,AttributeError):
        return error('invalid_description','Describe what you need to learn in 10 to 8,000 characters.',400)
    job_id=material.create(topic_id,description,name)
    if job_id is None: return error('not_found','Topic not found.',404)
    return {'generation_id':job_id}

@app.post('/api/material-generations/{job_id}/retry',status_code=202)
def retry_material(job_id:int):
    if not material.retry(job_id): return error('not_found','Failed generation not found.',404)
    return {'generation_id':job_id}

@app.delete('/api/material-generations/{job_id}')
def delete_material_job(job_id:int):
    with db() as c:
        if not c.execute("DELETE FROM material_generations WHERE id=? AND status='failed'",(job_id,)).rowcount:
            return error('not_found','Failed generation not found.',404)
    return {'ok':True}

@app.get('/api/files/{file_id}')
def download(file_id:int):
    with db() as c: f=c.execute('SELECT f.*,(SELECT g.description FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS generated_description,(SELECT g.requested_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS requested_name,(SELECT g.concept_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS concept_name FROM files f WHERE f.id=?',(file_id,)).fetchone()
    if not f or not Path(UPLOADS,f['storage_key']).exists(): return error('not_found','File not found.',404)
    if f['generated_description']:
        body=Path(UPLOADS,f['storage_key']).read_text(encoding='utf-8')
        filename=generated_filename(f['original_name'],f['generated_description'],f['requested_name'],f['concept_name'])
        return Response(content=generated_reference(body,f['generated_description'],filename),media_type='text/plain',headers={'Content-Disposition':"inline; filename*=UTF-8''"+quote(filename)})
    return FileResponse(Path(UPLOADS,f['storage_key']),media_type=f['mime_type'],filename=f['original_name'],content_disposition_type='inline')

@app.delete('/api/files/{file_id}')
def delete_file(file_id:int):
    with db() as c:
        f=c.execute('SELECT * FROM files WHERE id=?',(file_id,)).fetchone()
        if not f: return error('not_found','File not found.',404)
        for row in c.execute('SELECT id,sources_json FROM failed_cards WHERE subtopic_id IN (SELECT id FROM subtopics WHERE topic_id=?)',(f['topic_id'],)).fetchall():
            if any(s.get('file_id')==file_id for s in json.loads(row['sources_json'])): c.execute('DELETE FROM failed_cards WHERE id=?',(row['id'],))
        c.execute('DELETE FROM files WHERE id=?',(file_id,))
        c.execute('UPDATE topics SET index_revision=index_revision+1 WHERE id=?',(f['topic_id'],))
    Path(UPLOADS,f['storage_key']).unlink(missing_ok=True)
    return {'job_id':ingestion.enqueue(f['topic_id'])}

@app.post('/api/topics/{topic_id}/reindex',status_code=202)
def reindex(topic_id:int):
    job=ingestion.enqueue(topic_id)
    if job is None: return error('not_found','Topic not found.',404)
    return {'job_id':job}
@app.get('/api/jobs/{job_id}')
def job(job_id:int):
    with db() as c: row=c.execute('SELECT * FROM ingestion_jobs WHERE id=?',(job_id,)).fetchone()
    return dict(row) if row else error('not_found','Job not found.',404)

@app.post('/api/sessions')
async def create_session(request:Request):
    try:
        data=await request.json(); sid=study.create(data.get('scope_type'),int(data.get('scope_id')),data.get('saved_only') is True)
        return {'id':sid}
    except (ValueError,TypeError): return error('empty_scope','There is no indexed material to study in this selection.',400)
@app.get('/api/sessions/{sid}/next')
def next_card(sid:str):
    state,card=study.next_card(sid)
    if state=='expired': return error('session_expired','Session expired. Start a new session.',409)
    if state=='error': return error('generation_failed',card,503)
    if state=='loading': return JSONResponse({'status':'generating'},status_code=202)
    return card
@app.post('/api/sessions/{sid}/grade')
@app.post('/api/sessions/{sid}/skip')
async def grade(sid:str,request:Request):
    try:
        data=await request.json(); token=data['card_token']; known=None if request.url.path.endswith('/skip') else data['known']
        if known is not None and not isinstance(known,bool): raise ValueError()
    except (ValueError,KeyError,TypeError): return error('invalid_request','Invalid grade.',400)
    state,result=study.grade(sid,token,known)
    if state!='ok': return error('stale_session','This card or session is no longer current.',409)
    return result
@app.delete('/api/sessions/{sid}')
def end_session(sid:str):
    with study.lock: study.sessions.pop(sid,None)
    return {'ok':True}

@app.post('/api/sessions/{sid}/bookmark')
async def bookmark(sid:str,request:Request):
    try:
        data=await request.json()
        if not isinstance(data['saved'],bool): raise ValueError()
        state,result=study.bookmark(sid,data['card_token'],data['saved'])
    except (KeyError,ValueError,TypeError): return error('invalid_request','Invalid bookmark.',400)
    if state!='ok': return error('stale_session','This card is no longer current.',409)
    return result

@app.get('/api/files/{file_id}/preview')
def preview(file_id:int):
    with db() as c: row=c.execute('SELECT f.*,(SELECT g.description FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS generated_description,(SELECT g.requested_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS requested_name,(SELECT g.concept_name FROM material_generations g WHERE g.file_id=f.id ORDER BY g.id DESC LIMIT 1) AS concept_name FROM files f WHERE f.id=?',(file_id,)).fetchone()
    if not row: return error('not_found','File not found.',404)
    file=dict(row)
    try:
        content=ingestion.extract(file,preview=True)
    except (ValueError,OSError) as e: return error('preview_failed',str(e),422)
    return {'content':content[:500000],'truncated':len(content)>500000}
