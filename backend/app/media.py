import os, subprocess, json, wave, math, shutil, re
from pathlib import Path

FFMPEG = os.getenv('FFMPEG', 'ffmpeg')
if not shutil.which(FFMPEG):
    try:
        import imageio_ffmpeg
        FFMPEG=imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError: pass
FFPROBE = os.getenv('FFPROBE', 'ffprobe')
def run(args):
    r = subprocess.run([str(x) for x in args], capture_output=True, text=True)
    if r.returncode: raise RuntimeError('Media operation failed: ' + r.stderr[-1600:])
    return r.stdout
def ff(*args): return run([FFMPEG, '-hide_banner', '-loglevel', 'error', '-y', *args])
def probe(path):
    if not shutil.which(FFPROBE):
        # Native development fallback. Docker and production use ffprobe JSON.
        r=subprocess.run([FFMPEG,'-hide_banner','-i',str(path)],capture_output=True,text=True)
        m=re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)',r.stderr)
        if not m: raise ValueError('Cannot read media duration; install ffprobe. Interrupted WebM recordings may need remuxing.')
        h,mi,s=map(float,m.groups())
        streams=[]
        for line in r.stderr.splitlines():
            if 'Stream #' in line:
                if 'Video:' in line: streams.append({'codec_type':'video'})
                if 'Audio:' in line: streams.append({'codec_type':'audio'})
        return {'format':{'duration':h*3600+mi*60+s},'streams':streams}
    return json.loads(run([FFPROBE, '-v','error','-show_format','-show_streams','-of','json',path]))
def duration(path): return float(probe(path)['format']['duration'])
def plan(segments, total):
    """Partition source completely; round intervals to 30fps to bound drift."""
    result=[]; cursor=0.; final=0.
    for i, s in enumerate(segments):
        start=max(cursor, min(total, s['start']))
        if start > cursor + .001:
            length=round((start-cursor)*30)/30
            result.append(dict(id=None,source_start=cursor,source_end=start,final_start=final,final_end=final+length,tempo=1.,hold=0.,speech_end=final,review=False))
            final+=length
        end=min(total, max(start+.01, s['end']))
        span=end-start
        if span<=0: continue
        audio=s['audio_duration']; tempo=min(1.12,max(1.,audio/max(.01,span)))
        speech=audio/tempo
        length=math.ceil(max(span,speech)*30)/30
        hold=max(0.,length-span)
        result.append(dict(id=s['id'],source_start=start,source_end=end,final_start=final,final_end=final+length,tempo=tempo,hold=hold,speech_end=final+speech,review=hold>max(2.,span*.25)))
        final+=length; cursor=end
    if cursor<total:
        length=math.ceil((total-cursor)*30)/30
        result.append(dict(id=None,source_start=cursor,source_end=total,final_start=final,final_end=final+length,tempo=1.,hold=0.,speech_end=final,review=False))
    return result
def render_interval(source, audio, row, out):
    length=row['final_end']-row['final_start']; span=row['source_end']-row['source_start']
    # A sub-frame trailing gap can otherwise yield audio-only MP4 and break
    # concat stream ordering. Use the preceding frame for such intervals.
    seek=row['source_start'] if span>=1/30 else max(0,row['source_start']-1/30)
    args=['-ss',str(seek),'-t',str(max(span,1/30)),'-i',str(source)]
    args+=['-i',str(audio)] if audio else ['-f','lavfi','-i','anullsrc=r=48000:cl=mono']
    ff(*args,'-filter_complex',f"[0:v]setpts=PTS-STARTPTS,fps=30,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1,tpad=stop_mode=clone:stop_duration={row['hold']+.1},trim=duration={length}[v];[1:a]asetpts=PTS-STARTPTS,atempo={row['tempo']},aresample=48000,aformat=channel_layouts=mono,apad,atrim=duration={length}[a]",'-map','[v]','-map','[a]','-c:v','libx264','-preset','fast','-crf','20','-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-t',str(length),'-movflags','+faststart',str(out))
def stamp(t, vtt=False):
    n=round(t*1000); h,n=divmod(n,3600000); m,n=divmod(n,60000); s,ms=divmod(n,1000)
    return f'{h:02}:{m:02}:{s:02}{"." if vtt else ","}{ms:03}'
def subtitles(timeline, segments, vtt=False):
    by={s['id']:s for s in segments}; cues=[]
    for r in timeline:
        if r['id'] is None: continue
        # Divide into short, readable cues on the final speech timeline.
        words=by[r['id']]['english'].split(); chunks=[' '.join(words[i:i+12]) for i in range(0,len(words),12)]
        for i,text in enumerate(chunks):
            a=r['final_start']+(r['speech_end']-r['final_start'])*i/len(chunks)
            b=r['final_start']+(r['speech_end']-r['final_start'])*(i+1)/len(chunks)
            cues.append(f'{len(cues)+1}\n{stamp(a,vtt)} --> {stamp(b,vtt)}\n{text}\n')
    return ('WEBVTT\n\n' if vtt else '')+'\n'.join(cues)
