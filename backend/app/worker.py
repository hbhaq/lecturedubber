"""PostgreSQL jobs are durable; Redis is only delivery and mutual exclusion."""
import os, threading
from redis import Redis
from redis.exceptions import LockError
from rq import Queue, Worker
from sqlalchemy import select
from .db import init_db, Session, Job, Lecture, engine, now
from .pipeline import execute
from .activity import heartbeat

local_lock=threading.Lock()
def perform(jid):
    if os.getenv('LOCAL_WORKER')=='1':
        with local_lock,heartbeat(jid): execute(jid)
        return
    # RQ forks a work horse. Never reuse the parent's PostgreSQL/SSL sockets.
    engine.dispose(close=False)
    try:
        redis=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))
        with Session() as db:
            j=db.get(Job,jid)
            if not j or j.status in ('done','cancelled','running') or j.cancel: return
            lid=j.lecture_id
        with redis.lock('lecture:'+lid,timeout=28800,blocking_timeout=1),heartbeat(jid): execute(jid)
    except LockError:
        # Another delivery owns this lecture; never fail its active job.
        return
    except Exception as error:
        # Failures before execute() must not leave a permanently queued job.
        engine.dispose(close=False)
        with Session() as db:
            j=db.get(Job,jid)
            if j and j.status in ('queued','running'):
                from .activity import event
                j.status='failed';j.updated=now()
                j.error=type(error).__name__+': worker could not start or retain this job. Retry to resume cached work.'
                l=db.get(Lecture,j.lecture_id)
                if l: l.status='failed'
                event(db,j,j.stage,j.error);db.commit()
        raise

def restore_queued():
    """Redeliver durable queued jobs, including old failures before worker entry.

    Duplicate delivery is safe under the lecture lock and completed-job check.
    Running jobs require explicit recovery after the previous worker is stopped.
    """
    with Session() as db: ids=list(db.scalars(select(Job.id).where(Job.status=='queued',Job.cancel==False)))
    for jid in ids: enqueue(jid)
def enqueue(jid):
    if os.getenv('LOCAL_WORKER')=='1': threading.Thread(target=perform,args=(jid,),daemon=True).start()
    else:
        Queue(connection=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))).enqueue('app.worker.perform',jid,job_timeout=28800,result_ttl=86400)
def recover():
    # Run once only with no workers active, after a crash; HTTP endpoint enforces this via operator command.
    with Session() as db:
        jobs=db.scalars(select(Job).where(Job.status.in_(['running','queued']))).all()
        ids=[]
        for j in jobs: j.status='queued'; j.cancel=False; ids.append(j.id)
        db.commit()
    for jid in ids: enqueue(jid)
if __name__=='__main__':
    import sys
    init_db()
    if '--recover' in sys.argv: recover()
    else:
        restore_queued()
        Worker(['default'],connection=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))).work()
