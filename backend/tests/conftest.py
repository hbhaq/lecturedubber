import os, tempfile
from pathlib import Path
ROOT=Path(tempfile.mkdtemp(prefix='lecture-tests-'))
os.environ['DATABASE_URL']='sqlite:///'+str(ROOT/'test.db').replace('\\','/')
os.environ['STORAGE_ROOT']=str(ROOT/'media')
os.environ['LOCAL_WORKER']='1'
import pytest
from app.db import init_db, Base, engine
@pytest.fixture(autouse=True)
def database():
    Base.metadata.drop_all(engine);init_db();yield
