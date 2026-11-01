import time
import pytest
from fastapi.testclient import TestClient
from app import main, pipeline
from app.db import Session, Job, JobPulse, Segment
from app.activity import heartbeat
from app.storage import store

def test_sample_corrections_carry_into_full_editor(monkeypatch):
    monkeypatch.setattr(main,'enqueue',pipeline.execute)
    monkeypatch.setattr(pipeline,'ff',lambda *args: None)
    monkeypatch.setattr(pipeline,'probe',lambda _: {'streams':[{'codec_type':'video'}],'format':{'duration':60}})
    class STT:
        def transcribe(self,*_): return [{'start':0,'end':10,'original':'source','flags':[]}]
    class LLM:
        def translate(self,*_): return {'english':'translated','flags':[]}
    monkeypatch.setattr(pipeline,'adapters',lambda *_:(STT(),LLM(),None))
    with TestClient(main.app) as c:
        lid=c.post('/lectures',json={'title':'Editor test'}).json()['id']
        c.post(f'/lectures/{lid}/source',files={'file':('test.mp4',b'fixture','video/mp4')})
        store.path(f'{lid}/normalized.mkv').touch()
        assert c.post(f'/lectures/{lid}/jobs',json={'kind':'sample'}).status_code==200
        assert c.put(f'/lectures/{lid}/sample',json={'index':0,'original':'correct source','english':'correct English','acknowledged':True}).status_code==200
        assert c.post(f'/lectures/{lid}/jobs',json={'kind':'process'}).status_code==200
        data=c.get(f'/lectures/{lid}').json()
        assert len(data['segments'])==2
        assert data['segments'][0]['original']=='correct source'
        assert data['segments'][0]['english']=='correct English'
        assert data['segments'][1]['start']==30
        assert data['status']=='awaiting review'
        assert data['jobs'][0]['events'][-1]['message']=='Completed successfully'
        assert any('2/2' in e['message'] for e in data['jobs'][0]['events'])
        sid=data['segments'][0]['id']
        c.post(f'/lectures/{lid}/approve')
        c.put(f'/lectures/{lid}/segments/{sid}',json={'original':'another correction','english':'correct English'})
        assert c.get(f'/lectures/{lid}').json()['approved']==0
        assert c.delete(f'/lectures/{lid}').status_code==200
        with Session() as db:
            from app.db import JobEvent
            from sqlalchemy import select
            assert db.scalars(select(JobEvent)).all()==[]

def test_heartbeat_is_independent_of_completed_progress():
    with Session() as db:
        j=Job(lecture_id='fixture',kind='process',status='running');db.add(j);db.commit();jid=j.id;updated=j.updated
    with heartbeat(jid):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            with Session() as db:
                if db.get(JobPulse,jid): break
            time.sleep(.01)
    with Session() as db:
        assert db.get(JobPulse,jid).heartbeat
        assert db.get(Job,jid).updated==updated

def test_worker_entry_failure_is_durable_and_pool_is_replaced(monkeypatch):
    from app import worker
    monkeypatch.setenv('LOCAL_WORKER','0')
    with Session() as db:
        j=Job(lecture_id='fixture',kind='process');db.add(j);db.commit();jid=j.id
    calls=[];dispose=worker.engine.dispose
    def fresh(*,close=True): calls.append(close);dispose(close=close)
    monkeypatch.setattr(worker.engine,'dispose',fresh)
    class BrokenRedis:
        @staticmethod
        def from_url(_): raise RuntimeError('simulated queue failure')
    monkeypatch.setattr(worker,'Redis',BrokenRedis)
    with pytest.raises(RuntimeError): worker.perform(jid)
    assert calls==[False,False]
    with Session() as db:
        assert db.get(Job,jid).status=='failed'
        assert 'Retry' in db.get(Job,jid).error

def test_startup_redelivers_only_durable_queued_jobs(monkeypatch):
    from app import worker
    with Session() as db:
        queued=Job(lecture_id='x',kind='process',status='queued')
        db.add_all([queued,Job(lecture_id='y',kind='process',status='running'),Job(lecture_id='z',kind='process',status='done')]);db.commit();jid=queued.id
    sent=[];monkeypatch.setattr(worker,'enqueue',sent.append)
    worker.restore_queued();assert sent==[jid]

def test_duplicate_delivery_does_not_fail_active_job(monkeypatch):
    from app import worker
    monkeypatch.setenv('LOCAL_WORKER','0')
    with Session() as db:
        j=Job(lecture_id='fixture',kind='process',status='running');db.add(j);db.commit();jid=j.id
    monkeypatch.setattr(worker,'execute',lambda _:pytest.fail('duplicate must not execute'))
    worker.perform(jid)
    with Session() as db: assert db.get(Job,jid).status=='running'

