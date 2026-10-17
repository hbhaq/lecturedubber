import re, shutil
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.db import Session, Lecture, Segment, Job
from app.main import app
from app import main
from app.pipeline import execute, invalidate, audio_key
from app.storage import store
from app.media import plan, subtitles, ff, duration, probe

def test_mapping_preserves_gaps_and_bounds_tempo():
    seg=[{'id':'a','start':1,'end':4,'audio_duration':8,'english':'one two three'},{'id':'b','start':6,'end':10,'audio_duration':2,'english':'four five'}]
    result=plan(seg,12)
    assert result[0]['source_start']==0 and result[-1]['source_end']==12
    assert all(1<=r['tempo']<=1.12 for r in result)
    for a,b in zip(result,result[1:]):
        assert a['source_end']==b['source_start']
        assert a['final_end']==b['final_start']
    assert result[1]['review']
    assert result[1]['speech_end']<=result[1]['final_end']
    assert '00:00:01,000' in subtitles(result,seg)
    assert subtitles(result,seg,True).startswith('WEBVTT')
def test_long_timeline_has_no_cumulative_anchor_drift():
    seg=[{'id':str(i),'start':i*3,'end':i*3+2.7,'audio_duration':3.2} for i in range(1000)]
    result=plan(seg,3000)
    for a,b in zip(result,result[1:]): assert abs(a['final_end']-b['final_start'])<1e-9
    assert all(abs((r['final_end']-r['final_start'])*30-round((r['final_end']-r['final_start'])*30))<1e-7 for r in result)
def test_invalidation_is_segment_scoped_and_revokes_approval():
    l=Lecture(mode='demo',voice='coral',pronunciation='',revision=3,approved=3,preview='old',exports={'video':'old'})
    a=Segment(english='first',revision=1,audio_key='a');b=Segment(english='second',revision=1,audio_key='b')
    before=audio_key(l,b);invalidate(l,a)
    assert l.approved==0 and l.revision==4 and not l.preview and not l.exports
    assert a.audio_key=='' and b.audio_key=='b' and audio_key(l,b)==before
def test_approval_flags_origin_and_cross_lecture(monkeypatch):
    monkeypatch.setattr(main,'enqueue',lambda _:None)
    with TestClient(app) as c:
        l=c.post('/lectures',json={'title':'Test'}).json();lid=l['id']
        assert c.post(f'/lectures/{lid}/jobs',json={'kind':'preview'}).status_code==400
        with Session() as db:
            s=Segment(lecture_id=lid,start=0,end=2,original='source',english='translation',flags=['check']);db.add(s);db.commit();sid=s.id
        assert c.post(f'/lectures/{lid}/approve').status_code==400
        c.put(f'/lectures/{lid}/segments/{sid}',json={'english':'translation','acknowledged':True})
        assert c.post(f'/lectures/{lid}/approve').status_code==200
        c.put(f'/lectures/{lid}/segments/{sid}',json={'english':'edited','acknowledged':False})
        assert c.get(f'/lectures/{lid}').json()['approved']==0
        assert c.post('/lectures',json={'title':'x'},headers={'Origin':'https://evil.example'}).status_code==403
        other=c.post('/lectures',json={'title':'Other'}).json()['id']
        assert c.put(f'/lectures/{other}/segments/{sid}',json={'english':'bad'}).status_code==404
def test_cancelled_duplicate_job_does_nothing():
    with Session() as db:
        l=Lecture(title='Test');db.add(l);db.commit()
        j=Job(lecture_id=l.id,kind='process',status='cancelled',cancel=True);db.add(j);db.commit();jid=j.id
    execute(jid)
    with Session() as db: assert db.get(Job,jid).attempts==0
def test_real_media_demo_end_to_end_and_cached_recovery(monkeypatch,tmp_path):
    """Real FFmpeg + offline synthetic speech. Demo STT/translation, no live API."""
    monkeypatch.setattr(main,'enqueue',lambda _:None)
    fixture=tmp_path/'fixture.mp4'
    ff('-f','lavfi','-i','testsrc2=size=640x360:rate=30','-f','lavfi','-i','sine=frequency=440:sample_rate=48000','-t','4','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',fixture)
    with TestClient(app) as c:
        lid=c.post('/lectures',json={'title':'Modular inverse','course':'Cryptography','topic':'Arithmetic','mode':'demo'}).json()['id']
        with fixture.open('rb') as f: assert c.post(f'/lectures/{lid}/source',files={'file':('fixture.mp4',f,'video/mp4')}).status_code==200
        def stage(kind,**options):
            r=c.post(f'/lectures/{lid}/jobs',json={'kind':kind,**options});assert r.status_code==200,r.text
            execute(r.json()['id']);l=c.get(f'/lectures/{lid}').json()
            jobs={j['id']:j for j in l['jobs']};j=jobs[r.json()['id']]
            assert j['status']=='done',j
            return l
        stage('sample');l=stage('process');s=l['segments'][0]
        assert c.post(f'/lectures/{lid}/approve').status_code==400
        c.put(f'/lectures/{lid}/segments/{s["id"]}',json={'english':s['english'],'acknowledged':True})
        c.post(f'/lectures/{lid}/approve');l=stage('preview')
        assert l['timeline'][-1]['final_end']>=4
        preview=c.get(f'/lectures/{lid}/assets/preview',headers={'Range':'bytes=0-99'})
        assert preview.status_code==206 and len(preview.content)==100
        assert preview.headers['content-type']=='video/mp4'
        assert abs(duration(store.path(l['preview']))-l['timeline'][-1]['final_end'])<.25
        audio=store.path(l['segments'][0]['audio']);mtime=audio.stat().st_mtime_ns
        # Repeated preview reuses speech; render retry must not charge again.
        stage('preview');assert audio.stat().st_mtime_ns==mtime
        l=stage('export',accept_holds=True)
        assert set(l['exports'])=={'lecture.mp4','subtitles.srt','subtitles.vtt','transcript.md','transcript.txt','notes.md','notes.pdf','timeline.json'}
        for name in l['exports']: assert c.get(f'/lectures/{lid}/assets/{name}').status_code==200
        assert 'DEMO' in c.get(f'/lectures/{lid}/assets/transcript.txt').text
        assert store.path(l['exports']['notes.pdf']).read_bytes().startswith(b'%PDF')
        mp4=store.path(l['exports']['lecture.mp4'])
        metadata=probe(mp4);assert any(s['codec_type']=='video' for s in metadata['streams'])
        stage('export',accept_holds=True,burn_captions=True)
        # Deliberate downstream failure, then resume without regenerating paid audio.
        from app import pipeline
        original=pipeline.render_interval
        shutil.rmtree(store.path(lid+'/parts/placeholder').parent)
        monkeypatch.setattr(pipeline,'render_interval',lambda *a:(_ for _ in ()).throw(RuntimeError('Injected render failure')))
        r=c.post(f'/lectures/{lid}/jobs',json={'kind':'preview'});jid=r.json()['id'];execute(jid)
        assert next(j for j in c.get(f'/lectures/{lid}').json()['jobs'] if j['id']==jid)['status']=='failed'
        monkeypatch.setattr(pipeline,'render_interval',original)
        assert c.post(f'/jobs/{jid}/retry').status_code==200;execute(jid)
        assert audio.stat().st_mtime_ns==mtime
        # Editing makes every previously downloadable export unavailable.
        c.put(f'/lectures/{lid}/segments/{s["id"]}',json={'english':'Edited reviewed script.','acknowledged':True})
        assert c.get(f'/lectures/{lid}/assets/lecture.mp4').status_code==404

def test_browser_style_webm_without_duration_is_normalized(monkeypatch,tmp_path):
    monkeypatch.setattr(main,'enqueue',lambda _:None)
    webm=tmp_path/'browser.webm'
    ff('-f','lavfi','-i','testsrc2=size=320x180:rate=30','-f','lavfi','-i','sine=frequency=440','-t','2','-c:v','libvpx','-c:a','libopus','-live','1',webm)
    with TestClient(app) as c:
        lid=c.post('/lectures',json={'title':'WebM recovery test'}).json()['id']
        with webm.open('rb') as f: assert c.post(f'/lectures/{lid}/source',files={'file':('browser.webm',f,'video/webm')}).status_code==200
        jid=c.post(f'/lectures/{lid}/jobs',json={'kind':'sample'}).json()['id'];execute(jid)
        l=c.get(f'/lectures/{lid}').json()
        assert l['sample_ok'],l['jobs']
        assert 1.9<l['duration']<2.2
