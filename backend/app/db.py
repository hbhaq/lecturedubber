import os, uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, Float, Integer, Boolean, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

engine = create_engine(os.getenv('DATABASE_URL', 'sqlite:///./lecture.db'), **({'connect_args': {'check_same_thread': False}} if os.getenv('DATABASE_URL', 'sqlite:').startswith('sqlite:') else {}))
Session = sessionmaker(engine, expire_on_commit=False)
class Base(DeclarativeBase): pass
def uid(): return uuid.uuid4().hex
def now(): return datetime.now(timezone.utc).isoformat()
class Lecture(Base):
    __tablename__ = 'lectures'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    title: Mapped[str] = mapped_column(String)
    course: Mapped[str] = mapped_column(String, default='')
    topic: Mapped[str] = mapped_column(String, default='')
    context: Mapped[str] = mapped_column(Text, default='')
    glossary: Mapped[str] = mapped_column(Text, default='')
    pronunciation: Mapped[str] = mapped_column(Text, default='')
    voice: Mapped[str] = mapped_column(String, default='coral')
    mode: Mapped[str] = mapped_column(String, default='demo')
    status: Mapped[str] = mapped_column(String, default='uploading')
    source: Mapped[str] = mapped_column(String, default='')
    duration: Mapped[float] = mapped_column(Float, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    approved: Mapped[int] = mapped_column(Integer, default=0)
    sample_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    timeline: Mapped[list] = mapped_column(JSON, default=list)
    preview: Mapped[str] = mapped_column(String, default='')
    exports: Mapped[dict] = mapped_column(JSON, default=dict)
    created: Mapped[str] = mapped_column(String, default=now)
class Segment(Base):
    __tablename__ = 'segments'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    lecture_id: Mapped[str] = mapped_column(String, index=True)
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    original: Mapped[str] = mapped_column(Text)
    english: Mapped[str] = mapped_column(Text, default='')
    flags: Mapped[list] = mapped_column(JSON, default=list)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    audio_key: Mapped[str] = mapped_column(String, default='')
    audio: Mapped[str] = mapped_column(String, default='')
    audio_duration: Mapped[float] = mapped_column(Float, default=0)
class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    lecture_id: Mapped[str] = mapped_column(String, index=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default='queued')
    stage: Mapped[str] = mapped_column(String, default='queued')
    progress: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str] = mapped_column(Text, default='')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    cancel: Mapped[bool] = mapped_column(Boolean, default=False)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    usage: Mapped[list] = mapped_column(JSON, default=list)
    updated: Mapped[str] = mapped_column(String, default=now)
class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash: Mapped[str] = mapped_column(String, primary_key=True)
    expires: Mapped[float] = mapped_column(Float)
    credential_version: Mapped[str] = mapped_column(String)
class LoginGate(Base):
    __tablename__ = 'login_gate'
    id: Mapped[str] = mapped_column(String, primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_start: Mapped[float] = mapped_column(Float, default=0)
def init_db():
    Base.metadata.create_all(engine)
    with Session() as db:
        if not db.get(LoginGate,'admin'):
            db.add(LoginGate(id='admin',failures=0,window_start=0));db.commit()
