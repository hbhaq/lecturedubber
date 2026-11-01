"""Durable, content-free progress events and independent worker liveness."""
import logging, threading
from contextlib import contextmanager
from .db import Session, JobEvent, JobPulse, now

log=logging.getLogger('lecture.jobs')

def event(db,job,stage,message):
    db.add(JobEvent(job_id=job.id,stage=stage,message=message))
    log.warning('job=%s kind=%s stage=%s progress=%.0f%% %s',job.id,job.kind,stage,job.progress*100,message)

@contextmanager
def heartbeat(jid):
    stop=threading.Event()
    def beat():
        while not stop.is_set():
            try:
                with Session() as db:
                    db.merge(JobPulse(job_id=jid,heartbeat=now()));db.commit()
            except Exception:
                log.warning('job=%s heartbeat write failed',jid)
            stop.wait(5)
    thread=threading.Thread(target=beat,daemon=True);thread.start()
    try: yield
    finally: stop.set();thread.join(timeout=6)
