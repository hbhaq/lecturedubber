import os, shutil, mimetypes
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select
from .db import init_db, Session, Lecture, Segment, Job
from .storage import store
from .pipeline import rows, asdict, invalidate
from .worker import enqueue
from . import auth

@asynccontextmanager
async def lifespan(app):
    auth.validate_settings()
    init_db()
    yield
app=FastAPI(title='Lecture Studio',lifespan=lifespan)
origins=auth.origins()
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=True,allow_methods=['*'],allow_headers=['Content-Type','X-CSRF-Token','Range'])
from urllib.parse import urlsplit
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['localhost','127.0.0.1','api','testserver']+([urlsplit(auth.public_origin()).hostname] if auth.public_origin() else []))
@app.middleware('http')
async def local_origin(request:Request,call_next):
    return await auth.protect(request,call_next)
app.include_router(auth.router)
def get(db,lid,lock=False):
    q=select(Lecture).where(Lecture.id==lid)
    if lock: q=q.with_for_update()
    l=db.scalar(q)
    if not l: raise HTTPException(404,'Lecture not found')
    return l
def idle(db,lid):
    if db.scalar(select(Job).where(Job.lecture_id==lid,Job.status.in_(['queued','running']))): raise HTTPException(409,'A job is active. Cancel it and wait for it to stop before editing.')
class Create(BaseModel):
    title:str=Field(min_length=1,max_length=300)
    course:str=Field(default='',max_length=300)
    topic:str=Field(default='',max_length=300)
    context:str=Field(default='',max_length=12000)
    glossary:str=Field(default='',max_length=6000)
    mode:str='demo'
class Settings(BaseModel):
    voice:str='coral'
    pronunciation:str=Field(default='',max_length=3000)
class Edit(BaseModel):
    english:str=Field(min_length=1,max_length=4000)
    acknowledged:bool=False
class Start(BaseModel):
    kind:str
    burn_captions:bool=False
    accept_holds:bool=False
@app.get('/health')
def health(): return {'ok':True,'live_available':bool(os.getenv('OPENAI_API_KEY')),'cost_estimate':'Unavailable: no verified pricing configured. Provider usage is recorded where returned.','voices':['coral','alloy','sage']}
@app.get('/lectures')
def list_lectures():
    with Session() as db: return [asdict(l) for l in db.scalars(select(Lecture).order_by(Lecture.created.desc()))]
@app.post('/lectures')
def create(value:Create):
    if value.mode not in ('live','demo'): raise HTTPException(400,'Choose demo or live')
    if value.mode=='live' and not os.getenv('OPENAI_API_KEY'): raise HTTPException(400,'Set OPENAI_API_KEY on the backend or choose demo mode.')
    with Session() as db:
        l=Lecture(**value.model_dump()); db.add(l); db.commit(); return asdict(l)
@app.get('/lectures/{lid}')
def detail(lid:str):
    with Session() as db:
        l=get(db,lid); jobs=db.scalars(select(Job).where(Job.lecture_id==lid).order_by(Job.updated.desc())).all()
        return {**asdict(l),'segments':[asdict(s) for s in rows(db,lid)],'jobs':[asdict(j) for j in jobs],'sample':store.json(f'{lid}/sample.json')}
@app.post('/lectures/{lid}/source')
def upload(lid:str,file:UploadFile):
    # UploadFile is spooled to disk by Starlette; copy in bounded chunks.
    with Session() as db:
        l=get(db,lid,True); idle(db,lid)
        if l.source: raise HTTPException(409,'Source is immutable. Create a new lecture for another recording.')
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in ('.mp4','.webm','.mov','.mkv','.m4v'): raise HTTPException(400,'Use MP4, WebM, MOV, MKV or M4V video.')
        key=f'{lid}/source{suffix}'; p=store.path(key); tmp=p.with_suffix('.upload')
        with tmp.open('wb') as dest: shutil.copyfileobj(file.file,dest,1024*1024)
        tmp.replace(p); l.source=key; l.status='uploaded'; db.commit(); return {'source':key}
@app.put('/lectures/{lid}/settings')
def settings(lid:str,value:Settings):
    if value.voice not in ('coral','alloy','sage'): raise HTTPException(400,'Unsupported voice')
    with Session() as db:
        l=get(db,lid,True); idle(db,lid)
        if l.voice!=value.voice or l.pronunciation!=value.pronunciation:
            l.voice=value.voice; l.pronunciation=value.pronunciation; invalidate(l)
        db.commit(); return asdict(l)
@app.put('/lectures/{lid}/segments/{sid}')
def edit(lid:str,sid:str,value:Edit):
    with Session() as db:
        l=get(db,lid,True); idle(db,lid); s=db.get(Segment,sid)
        if not s or s.lecture_id!=lid: raise HTTPException(404,'Segment not found')
        if not value.english.strip(): raise HTTPException(400,'Segment must contain narration')
        if s.english!=value.english: s.english=value.english; invalidate(l,s)
        s.acknowledged=value.acknowledged; db.commit(); return asdict(s)
@app.post('/lectures/{lid}/approve')
def approve(lid:str):
    with Session() as db:
        l=get(db,lid,True); idle(db,lid); segments=rows(db,lid)
        if not segments or any(not s.english.strip() for s in segments): raise HTTPException(400,'Review a complete English script first')
        if any(s.flags and not s.acknowledged for s in segments): raise HTTPException(400,'Acknowledge every flagged passage before approval')
        l.approved=l.revision; l.status='approved'; db.commit(); return asdict(l)
@app.post('/lectures/{lid}/regenerate/{sid}')
def regenerate(lid:str,sid:str):
    with Session() as db:
        l=get(db,lid,True); idle(db,lid); s=db.get(Segment,sid)
        if not s or s.lecture_id!=lid: raise HTTPException(404,'Segment not found')
        if l.approved!=l.revision: raise HTTPException(409,'Approve the script first')
        if s.audio: store.path(s.audio).unlink(missing_ok=True)
        s.audio=''; s.audio_key=''; l.preview=''; l.exports={}; l.timeline=[]; db.commit()
    return start(lid,Start(kind='preview'))
@app.post('/lectures/{lid}/jobs')
def start(lid:str,value:Start):
    if value.kind not in ('sample','process','preview','export','voice_preview'): raise HTTPException(400,'Invalid job kind')
    with Session() as db:
        l=get(db,lid,True); idle(db,lid)
        if not l.source and value.kind!='voice_preview': raise HTTPException(400,'Upload or record a video first')
        if value.kind=='process' and not l.sample_ok: raise HTTPException(400,'Run and inspect a 30 second sample first')
        if value.kind=='process' and rows(db,lid): raise HTTPException(409,'Transcript already exists. Resume failed work instead of replacing reviewed content.')
        if value.kind=='preview' and l.approved!=l.revision: raise HTTPException(409,'Approve script before paid narration')
        if value.kind=='export' and not l.preview: raise HTTPException(409,'Review a synchronized preview first')
        j=Job(lecture_id=lid,kind=value.kind,options=value.model_dump()); db.add(j); db.commit(); jid=j.id
    try: enqueue(jid)
    except Exception:
        with Session() as db:
            j=db.get(Job,jid); j.status='failed'; j.error='Queue unavailable. Start Redis/worker, then retry.'; db.commit()
        raise HTTPException(503,'Queue unavailable; job saved for retry')
    return {'id':jid}
@app.post('/jobs/{jid}/cancel')
def cancel(jid:str):
    with Session() as db:
        j=db.get(Job,jid)
        if not j: raise HTTPException(404,'Job not found')
        j.cancel=True
        if j.status=='queued': j.status='cancelled'
        db.commit(); return asdict(j)
@app.post('/jobs/{jid}/retry')
def retry_job(jid:str):
    with Session() as db:
        j=db.get(Job,jid)
        if not j: raise HTTPException(404,'Job not found')
        get(db,j.lecture_id,True); idle(db,j.lecture_id)
        if j.status not in ('failed','cancelled'): raise HTTPException(409,'Only failed or cancelled jobs can be resumed')
        j.status='queued'; j.cancel=False; j.error=''; db.commit()
    enqueue(jid); return {'id':jid}
@app.get('/lectures/{lid}/assets/{asset}')
def asset(lid:str,asset:str):
    with Session() as db:
        l=get(db,lid)
        allowed={'source':l.source,'preview':l.preview,**l.exports}
        if asset=='voice.wav': allowed[asset]=f'{lid}/voice-{l.voice}.wav'
        key=allowed.get(asset)
        if not key or not store.path(key).is_file(): raise HTTPException(404,'Asset unavailable or outdated')
        name=Path(key).name if asset=='source' else 'preview.mp4' if asset=='preview' else asset
        return FileResponse(store.path(key),filename=name,media_type=mimetypes.guess_type(key)[0] or 'application/octet-stream',content_disposition_type='inline' if asset in ('source','preview','voice.wav','lecture.mp4') else 'attachment')
@app.delete('/lectures/{lid}')
def remove(lid:str):
    with Session() as db:
        l=get(db,lid,True); idle(db,lid)
        for s in rows(db,lid): db.delete(s)
        for j in db.scalars(select(Job).where(Job.lecture_id==lid)): db.delete(j)
        root=store.path(lid+'/placeholder').parent
        if root.is_relative_to(store.root) and root!=store.root: shutil.rmtree(root)
        db.delete(l); db.commit(); return {'deleted':True}
