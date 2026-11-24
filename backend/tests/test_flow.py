import os, tempfile, time
os.environ['DATA_DIR']=tempfile.mkdtemp()
os.environ['SESSION_SECRET']='test-secret'
from argon2 import PasswordHasher
os.environ['PASSWORD_HASH']=PasswordHasher().hash('correct')
from fastapi.testclient import TestClient
from app.main import app
from app import ingestion, study
import numpy as np

def fake_embedding(texts):
    return np.tile(np.array([1.,0.,0.],dtype=np.float32),(len(texts),1))

def fake_generate(prompt):
    if 'Organize' in prompt: return {'subtopics':[{'existing_id':None,'name':'Motion','description':'Motion models'}]}
    import re
    return {'front':'What is motion?', 'back':'A change in position.', 'source_chunk_ids':[int(re.search(r'\[chunk (\d+)\]',prompt).group(1))]}

ingestion.embeddings=fake_embedding
ingestion.generate=fake_generate
study.embeddings=fake_embedding
study.generate=fake_generate

def test_complete_flow():
    with TestClient(app,base_url='https://testserver',headers={'origin':'https://testserver'}) as c:
        assert c.get('/api/tree').status_code==401
        assert c.post('/api/login',json={'password':'wrong'}).status_code==401
        assert c.post('/api/login',json={'password':'correct'}).status_code==200
        course=c.post('/api/courses',json={'name':'Robotics'}).json()['id']
        topic=c.post(f'/api/courses/{course}/topics',json={'name':'Motion'}).json()['id']
        upload=c.post(f'/api/topics/{topic}/files',files={'files':('notes.txt',b'Motion is change in position over time.','text/plain')})
        assert upload.status_code==202,upload.text
        for _ in range(100):
            tree=c.get('/api/tree').json(); t=tree[0]['topics'][0]
            if t['index_status'] in ('ready','error'): break
            time.sleep(.05)
        assert t['index_status']=='ready',t
        assert t['proficiency']==.5 and len(t['subtopics'])==1
        sid=c.post('/api/sessions',json={'scope_type':'course','scope_id':course}).json()['id']
        for _ in range(100):
            card=c.get(f'/api/sessions/{sid}/next')
            if card.status_code!=202: break
            time.sleep(.05)
        assert card.status_code==200,card.text
        card=card.json(); token=card['card_token']
        grade=c.post(f'/api/sessions/{sid}/grade',json={'card_token':token,'known':False})
        assert grade.status_code==200 and abs(grade.json()['proficiency']-.4)<1e-8
        repeat=c.post(f'/api/sessions/{sid}/grade',json={'card_token':token,'known':False})
        assert repeat.json()==grade.json()
        assert abs(c.get('/api/tree').json()[0]['proficiency']-.4)<1e-8
        assert c.delete('/api/files/'+str(upload.json()['files'][0]['id'])).status_code==200
        assert c.get('/api/files/'+str(upload.json()['files'][0]['id'])).status_code==404
