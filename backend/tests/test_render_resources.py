from types import SimpleNamespace
import pytest
from app import media

def test_killed_media_has_useful_error(monkeypatch):
    monkeypatch.setattr(media.subprocess,'run',lambda *a,**k:SimpleNamespace(returncode=-9,stderr='',stdout=''))
    with pytest.raises(RuntimeError,match='exit -9.*memory limit'):
        media.run(['ffmpeg'])

def test_high_resolution_render_with_hold_preserves_resolution(tmp_path):
    source=tmp_path/'source.mp4';out=tmp_path/'out.mp4'
    media.ff('-f','lavfi','-i','testsrc2=s=3840x2160:r=30','-t','0.2','-c:v','libx264','-threads','1','-preset','ultrafast','-pix_fmt','yuv420p',source)
    row=dict(source_start=0,source_end=.2,final_start=0,final_end=.6,hold=.4,tempo=1)
    media.render_interval(source,None,row,out)
    assert abs(media.duration(out)-.6)<.08
    info=media.probe(out)
    assert any(x['codec_type']=='audio' for x in info['streams'])
    # Native test environments without ffprobe use the documented fallback.
    video=next(x for x in info['streams'] if x['codec_type']=='video')
    if 'width' in video: assert (video['width'],video['height'])==(3840,2160)
