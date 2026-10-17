import os, json, math, shutil
from pathlib import Path
from sqlalchemy import select, delete
from .db import Session, Lecture, Segment, Job, now
from .storage import store, digest
from .providers import adapters, STT_MODEL, LLM_MODEL, TTS_MODEL
from .media import ff, duration, probe, plan, render_interval, subtitles, stamp

class Cancelled(Exception): pass
def rows(db,lid): return db.scalars(select(Segment).where(Segment.lecture_id==lid).order_by(Segment.start,Segment.id)).all()
def asdict(s): return {c.name:getattr(s,c.name) for c in s.__table__.columns}
def audio_key(l,s): return digest(l.mode,TTS_MODEL if l.mode=='live' else 'espeak-v1',s.english,l.voice,l.pronunciation)
def invalidate(l,s=None):
    l.revision+=1; l.approved=0; l.preview=''; l.exports={}; l.timeline=[]; l.status='awaiting review'
    if s: s.revision+=1; s.audio_key=''; s.audio=''; s.audio_duration=0; s.acknowledged=False
def checkpoint(jid,stage,p):
    with Session() as db:
        j=db.get(Job,jid)
        if j.cancel: raise Cancelled()
        j.stage=stage; j.progress=p; j.updated=now(); db.commit()
        l=db.get(Lecture,j.lecture_id); l.status=stage; db.commit()
def execute(jid):
    with Session() as db:
        j=db.get(Job,jid)
        if not j or j.status in ('done','cancelled') or j.cancel: return
        j.status='running'; j.attempts+=1; j.error=''; j.updated=now(); db.commit()
        l=db.get(Lecture,j.lecture_id); lid=l.id
        def usage(value):
            with Session() as u:
                q=u.get(Job,jid); q.usage=[*q.usage,value]; u.commit()
        stt,llm,tts=adapters(l.mode,usage)
        root=store.path(lid+'/placeholder').parent
        try:
            if j.kind in ('sample','process'):
                checkpoint(jid,'extracting audio',.05)
                # Browser MediaRecorder WebM often lacks duration metadata.
                source=store.path(f'{lid}/normalized.mkv')
                if not source.exists():
                    tmp=source.with_suffix('.partial.mkv')
                    ff('-fflags','+genpts','-i',store.path(l.source),'-map','0:v:0','-map','0:a:0','-c','copy',tmp)
                    tmp.replace(source)
                info=probe(source)
                if not any(s['codec_type']=='video' for s in info['streams']): raise ValueError('Source needs a video stream.')
                l.duration=float(info['format']['duration']); db.commit()
                maximum=float(os.getenv('MAX_LECTURE_SECONDS','0'))
                if maximum and l.duration>maximum:
                    raise ValueError(f'Trial recordings are limited to {maximum:g} seconds. Delete this lecture and upload a shorter test video. No transcription request was made.')
                total=min(30.,l.duration) if j.kind=='sample' else l.duration
                all_segments=[]
                for index in range(math.ceil(total/300)):
                    checkpoint(jid,'transcribing',.1+.5*index/max(1,math.ceil(total/300)))
                    offset=index*300; length=min(300,total-offset)
                    wav=root/f'input-{index}-{length:.2f}.wav'
                    if not wav.exists(): ff('-ss',str(offset),'-t',str(length),'-i',source,'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',wav)
                    # 300 seconds PCM mono = 9.6 MB, below 25 MB per request.
                    key=f'{lid}/cache/stt-{digest(l.mode,STT_MODEL,index,length,l.glossary)}.json'
                    data=store.json(key)
                    if data is None: data=stt.transcribe(wav,l.glossary); store.json(key,data)
                    previous=offset
                    for s in data:
                        start=max(previous,offset+float(s['start'])); end=min(total,offset+float(s['end']))
                        if end<=start or not s['original'].strip(): continue
                        all_segments.append(dict(start=start,end=end,original=s['original'],flags=s.get('flags',[])))
                        previous=end
                if not all_segments: raise ValueError('No speech segments returned. Listen to the source and check microphone audio.')
                checkpoint(jid,'translating',.65)
                translated=[]
                for i,s in enumerate(all_segments):
                    checkpoint(jid,'translating',.65+.3*i/len(all_segments))
                    key=f'{lid}/cache/translate-{digest(l.mode,LLM_MODEL,s["original"],l.context,l.glossary)}.json'
                    t=store.json(key)
                    if t is None: t=llm.translate(s['original'],l.context,l.glossary); store.json(key,t)
                    if not t['english'].strip() or len(t['english'])>4000: raise ValueError('Translation segment is empty or exceeds 4000 characters; split source into shorter intervals.')
                    translated.append({**s,'english':t['english'],'flags':s['flags']+t['flags']})
                if j.kind=='sample':
                    store.json(f'{lid}/sample.json',translated); l.sample_ok=True; l.status='sample ready'
                else:
                    db.execute(delete(Segment).where(Segment.lecture_id==lid))
                    for s in translated: db.add(Segment(lecture_id=lid,**s))
                    l.status='awaiting review'; l.approved=0
                db.commit()
            elif j.kind=='voice_preview':
                checkpoint(jid,'voice preview',.2)
                path=store.path(f'{lid}/voice-{l.voice}.wav')
                if not path.exists():
                    tmp=path.with_suffix('.partial.wav')
                    tts.speak('The modular inverse helps us solve equations in modular arithmetic.',l.voice,l.pronunciation,tmp); tmp.replace(path)
                l.status='voice preview ready'; db.commit()
            elif j.kind=='preview':
                if l.approved!=l.revision: raise ValueError('Approve the current script before generating narration.')
                segments=rows(db,lid)
                if not segments: raise ValueError('No reviewed segments.')
                for i,s in enumerate(segments):
                    checkpoint(jid,'generating narration',.05+.45*i/len(segments))
                    key=audio_key(l,s); asset=f'{lid}/audio/{key}.wav'; path=store.path(asset)
                    if not path.exists():
                        tmp=path.with_suffix('.partial.wav'); tts.speak(s.english,l.voice,l.pronunciation,tmp)
                        duration(tmp); tmp.replace(path)
                    s.audio=asset; s.audio_key=key; s.audio_duration=duration(path); db.commit()
                checkpoint(jid,'aligning',.55)
                timeline=plan([asdict(s) for s in segments],l.duration)
                l.timeline=timeline; db.commit()
                checkpoint(jid,'rendering preview',.6)
                rev=f'{lid}/versions/{l.revision}'; parts=[]; by={s.id:s for s in segments}
                for i,r in enumerate(timeline):
                    checkpoint(jid,'rendering preview',.6+.35*i/len(timeline))
                    key=digest(r,by[r['id']].audio_key if r['id'] else 'silence')
                    part=store.path(f'{lid}/parts/{key}.mp4')
                    if not part.exists():
                        tmp=part.with_suffix('.partial.mp4')
                        render_interval(store.path(f'{lid}/normalized.mkv'),store.path(by[r['id']].audio) if r['id'] else None,r,tmp)
                        tmp.replace(part)
                    parts.append(part)
                listing=store.path(rev+'/concat.txt')
                listing.write_text('\n'.join("file '"+str(p).replace('\\','/').replace("'","'\\''")+"'\nduration "+str(r['final_end']-r['final_start']) for p,r in zip(parts,timeline)),'utf-8')
                preview=rev+'/preview.mp4'; out=store.path(preview); tmp=out.with_suffix('.partial.mp4')
                ff('-f','concat','-safe','0','-i',listing,'-c','copy','-movflags','+faststart',tmp); tmp.replace(out)
                if abs(duration(out)-timeline[-1]['final_end'])>.25: raise ValueError('Rendered timeline drift exceeds 250 ms; inspect source timing.')
                l.preview=preview; l.status='preview ready'; db.commit()
            elif j.kind=='export':
                if l.approved!=l.revision or not l.preview: raise ValueError('Generate and review a current preview first.')
                if any(r['review'] for r in l.timeline) and not j.options.get('accept_holds'): raise ValueError('Review and accept long frame holds before export.')
                checkpoint(jid,'rendering',.1)
                segments=[asdict(s) for s in rows(db,lid)]; folder=f'{lid}/versions/{l.revision}'
                export={}
                def write(name,text):
                    key=folder+'/'+name; store.path(key).write_text(text,'utf-8'); export[name]=key
                write('subtitles.srt',subtitles(l.timeline,segments)); write('subtitles.vtt',subtitles(l.timeline,segments,True))
                timing={r['id']:r for r in l.timeline if r['id']}
                body='\n\n'.join(f"[{stamp(timing[s['id']]['final_start'],True)}] {s['english']}" for s in segments)
                write('transcript.md',f'# {l.title}\n\n{body}'); write('transcript.txt',l.title+'\n\n'+body)
                # Bounded batches, cached independently; no full lecture context request.
                sections=[]; recaps=[]
                for i in range(0,len(segments),20):
                    checkpoint(jid,'creating notes',.3+.4*i/len(segments))
                    batch=[{'id':s['id'],'english':s['english']} for s in segments[i:i+20]]
                    key=f'{lid}/cache/notes-{digest(l.mode,LLM_MODEL,batch,l.title,l.topic)}.json'
                    notes=store.json(key)
                    if notes is None: notes=llm.notes(batch,l.title,l.topic); store.json(key,notes)
                    allowed={s['id'] for s in batch}
                    for sec in notes['sections']:
                        if not sec['segment_ids'] or not set(sec['segment_ids'])<=allowed: raise ValueError('Notes have invalid source citations; retry notes generation.')
                    sections+=notes['sections']; recaps.append(notes['recap'])
                md=f'# {l.title}\n\nCourse: {l.course}\n\nTopic: {l.topic}\n\n'+('**DEMO: no live AI processing.**\n\n' if l.mode=='demo' else '')
                for sec in sections:
                    t=min(timing[x]['final_start'] for x in sec['segment_ids'])
                    md+=f"## {sec['heading']}\n\n[Watch at {stamp(t,True)}](lecture.mp4#t={t:.3f})\n\n{sec['content']}\n\n"
                md+='## Recap\n\n'+'\n\n'.join(recaps)
                write('notes.md',md)
                from .documents import notes_pdf
                pdf=store.path(folder+'/notes.pdf');notes_pdf(pdf,md);export['notes.pdf']=folder+'/notes.pdf'
                write('timeline.json',json.dumps(l.timeline,indent=2))
                video=store.path(folder+'/lecture.mp4')
                if j.options.get('burn_captions'):
                    # Relative filter path avoids Windows drive-colon escaping.
                    import subprocess
                    from .media import FFMPEG
                    r=subprocess.run([FFMPEG,'-hide_banner','-loglevel','error','-y','-i','preview.mp4','-vf','subtitles=subtitles.srt','-c:v','libx264','-crf','20','-pix_fmt','yuv420p','-c:a','copy','-movflags','+faststart','lecture.mp4'],cwd=video.parent,capture_output=True,text=True)
                    if r.returncode: raise RuntimeError('Caption burn failed; check FFmpeg libass support: '+r.stderr[-800:])
                else: shutil.copyfile(store.path(l.preview),video)
                export['lecture.mp4']=folder+'/lecture.mp4'; l.exports=export; l.status='ready'; db.commit()
            j=db.get(Job,jid); db.refresh(j); j.status='done'; j.stage=l.status; j.progress=1; j.updated=now(); db.commit()
        except Exception as e:
            db.rollback(); j=db.get(Job,jid); l=db.get(Lecture,lid)
            j.status='cancelled' if isinstance(e,Cancelled) else 'failed'
            # Do not include provider response bodies or lecture text in errors.
            if isinstance(e,(ValueError,RuntimeError,Cancelled)): j.error=str(e)[:1800]
            else: j.error=type(e).__name__+': stage failed. Check credentials, quota, connectivity and provider availability; retry resumes cached work.'
            j.updated=now(); l.status=j.status; db.commit()
