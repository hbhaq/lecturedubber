from fastapi.testclient import TestClient
from app.main import app
from app import main
from app.storage import store

def test_trial_lecture_and_upload_limits(monkeypatch):
    monkeypatch.setenv('MAX_LECTURES','1');monkeypatch.setenv('MAX_UPLOAD_BYTES','10')
    with TestClient(app) as c:
        first=c.post('/lectures',json={'title':'Short test'});assert first.status_code==200
        lid=first.json()['id']
        assert c.post('/lectures',json={'title':'Another'}).status_code==409
        r=c.post(f'/lectures/{lid}/source',files={'file':('test.mp4',b'01234567890','video/mp4')})
        assert r.status_code==413
        assert c.get(f'/lectures/{lid}').json()['source']==''
        assert not store.path(f'{lid}/source.upload').exists()
        assert c.delete(f'/lectures/{lid}').status_code==200
        assert c.post('/lectures',json={'title':'Next'}).status_code==200

def test_duration_limit_stops_before_paid_transcription(monkeypatch,tmp_path):
    from app import pipeline
    from app.media import ff
    monkeypatch.setenv('MAX_LECTURE_SECONDS','1')
    monkeypatch.setattr(main,'enqueue',lambda _:None)
    called=[]
    from app.providers import DemoSTT
    monkeypatch.setattr(DemoSTT,'transcribe',lambda *args:called.append(True))
    video=tmp_path/'long.mp4'
    ff('-f','lavfi','-i','color=size=320x180:rate=30','-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libx264','-c:a','aac',video)
    with TestClient(app) as c:
        lid=c.post('/lectures',json={'title':'Over trial limit'}).json()['id']
        with video.open('rb') as f: c.post(f'/lectures/{lid}/source',files={'file':('long.mp4',f,'video/mp4')})
        jid=c.post(f'/lectures/{lid}/jobs',json={'kind':'sample'}).json()['id'];pipeline.execute(jid)
        job=next(j for j in c.get(f'/lectures/{lid}').json()['jobs'] if j['id']==jid)
        assert job['status']=='failed' and 'limited to 1 seconds' in job['error']
        assert not called
