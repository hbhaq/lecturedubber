"""PostgreSQL jobs are durable; Redis is only delivery and mutual exclusion."""
import os, threading
from redis import Redis
from rq import Queue, Worker
from sqlalchemy import select
from .db import init_db, Session, Job
from .pipeline import execute

local_lock=threading.Lock()
def perform(jid):
    if os.getenv('LOCAL_WORKER')=='1':
        with local_lock: execute(jid)
        return
    redis=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))
    with Session() as db: lid=db.get(Job,jid).lecture_id
    with redis.lock('lecture:'+lid,timeout=28800,blocking_timeout=1): execute(jid)
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
    else: Worker(['default'],connection=Redis.from_url(os.getenv('REDIS_URL','redis://redis:6379/0'))).work()
