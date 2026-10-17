import os,time
from sqlalchemy import text
from redis import Redis
from app.auth import validate_settings
from app.db import engine,init_db

# Fail closed: this image must never run as an unauthenticated public service.
os.environ['AUTH_REQUIRED']='true'
if not os.getenv('PUBLIC_ORIGIN') and os.getenv('RAILWAY_PUBLIC_DOMAIN'):
    os.environ['PUBLIC_ORIGIN']='https://'+os.environ['RAILWAY_PUBLIC_DOMAIN']
if not os.getenv('PUBLIC_ORIGIN'): raise RuntimeError('Set RAILWAY_PUBLIC_DOMAIN or PUBLIC_ORIGIN before exposing this service.')
if not os.getenv('DATABASE_URL','').startswith(('postgresql://','postgresql+psycopg://')):
    raise RuntimeError('Configure PostgreSQL DATABASE_URL; the trial image does not use ephemeral SQLite.')
validate_settings()
# app.db normalizes Railway's postgresql:// URL to the psycopg driver.
for attempt in range(30):
    try:
        with engine.connect() as connection: connection.execute(text('SELECT 1'))
        Redis.from_url(os.environ['REDIS_URL']).ping()
        init_db();break
    except Exception:
        if attempt==29: raise RuntimeError('Database or Redis is not ready. Check private service references.') from None
        time.sleep(2)
os.makedirs(os.environ['STORAGE_ROOT'],exist_ok=True)
os.execvp('supervisord',['supervisord','-c','/etc/supervisor/lecture.conf'])
