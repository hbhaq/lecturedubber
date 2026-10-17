"""Single administrator, opaque DB-backed sessions, CSRF and login throttling."""
import os, time, hashlib, hmac, secrets, base64
from urllib.parse import urlsplit
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, delete
from .db import Session, LoginSession, LoginGate

router=APIRouter(prefix='/auth')
TTL=8*60*60
def required(): return os.getenv('AUTH_REQUIRED','false').lower()=='true'
def public_origin(): return os.getenv('PUBLIC_ORIGIN','').rstrip('/')
def origins():
    origin=public_origin()
    return [origin] if origin else ['http://localhost:3000','http://127.0.0.1:3000']
def secure(): return public_origin().startswith('https://')
def cookie_name(): return '__Host-lecture_session' if secure() else 'lecture_session'
def token_hash(token): return hashlib.sha256(token.encode()).hexdigest()
def credential_version(): return token_hash(os.getenv('ADMIN_USERNAME','admin')+':'+os.getenv('ADMIN_PASSWORD_HASH',''))
def csrf(token): return token_hash('csrf:'+token)
def password_hash(password):
    salt=secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32,maxmem=64*1024*1024)
    return 'scrypt.'+base64.urlsafe_b64encode(salt+key).decode()
def verify(password,encoded):
    try:
        if not encoded.startswith('scrypt.'): return False
        data=base64.b64decode(encoded[7:],altchars=b'-_',validate=True)
        if len(data)!=48: return False
        key=hashlib.scrypt(password.encode(),salt=data[:16],n=16384,r=8,p=1,dklen=32,maxmem=64*1024*1024)
        return hmac.compare_digest(key,data[16:])
    except (ValueError,TypeError): return False
def validate_settings():
    origin=public_origin()
    if origin:
        url=urlsplit(origin)
        if url.scheme!='https' or not url.hostname or url.path or url.query or url.fragment or url.username or url.password:
            raise RuntimeError('PUBLIC_ORIGIN must be a bare HTTPS origin, e.g. https://lectures.example.com')
        if not required(): raise RuntimeError('Public deployment requires AUTH_REQUIRED=true')
    if required():
        value=os.getenv('ADMIN_PASSWORD_HASH','')
        try: valid=value.startswith('scrypt.') and len(base64.b64decode(value[7:],altchars=b'-_',validate=True))==48
        except ValueError: valid=False
        if not valid: raise RuntimeError('Configure ADMIN_PASSWORD_HASH using scripts/configure-admin.py before enabling authentication')
def session(request):
    token=request.cookies.get(cookie_name(),'')
    if len(token)>200 or not token: return None
    with Session() as db:
        value=db.get(LoginSession,token_hash(token))
        if value and value.expires>time.time() and hmac.compare_digest(value.credential_version,credential_version()): return token
    return None
async def protect(request,call_next):
    safe=request.method in ('GET','HEAD','OPTIONS')
    origin=request.headers.get('origin')
    if not safe and origin is not None and origin not in origins():
        return JSONResponse({'detail':'Untrusted origin'},status_code=403)
    public=request.url.path in ('/health','/auth/session','/auth/login')
    if required() and request.method!='OPTIONS':
        if request.url.path=='/auth/login' and origin not in origins():
            return JSONResponse({'detail':'Sign in from the application page'},status_code=403)
        if not public:
            token=session(request)
            if not token: return JSONResponse({'detail':'Sign in required'},status_code=401)
            if not safe and (origin not in origins() or not hmac.compare_digest(request.headers.get('x-csrf-token',''),csrf(token))):
                return JSONResponse({'detail':'Invalid request verification token. Reload and try again.'},status_code=403)
    response=await call_next(request)
    response.headers['Cache-Control']='no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response
class Credentials(BaseModel):
    username: str=Field(max_length=100)
    password: str=Field(max_length=256)
@router.get('/session')
def status(request:Request):
    token=session(request) if required() else None
    return {'required':required(),'authenticated':bool(token) or not required(),'username':os.getenv('ADMIN_USERNAME','admin') if token else None,'csrf':csrf(token) if token else ''}
@router.post('/login')
def login(value:Credentials,request:Request,response:Response):
    if not required(): raise HTTPException(400,'Authentication is not enabled locally')
    now=time.time()
    with Session() as db:
        gate=db.scalar(select(LoginGate).where(LoginGate.id=='admin').with_for_update())
        if now-gate.window_start>=60: gate.window_start=now;gate.failures=0
        if gate.failures>=5: raise HTTPException(429,'Too many sign-in attempts. Wait one minute.',headers={'Retry-After':'60'})
        # Always derive the password key, even for unknown usernames.
        valid=verify(value.password,os.environ['ADMIN_PASSWORD_HASH'])
        if not hmac.compare_digest(value.username.encode(),os.getenv('ADMIN_USERNAME','admin').encode()) or not valid:
            gate.failures+=1;db.commit();raise HTTPException(401,'Incorrect username or password')
        gate.failures=0
        old=request.cookies.get(cookie_name(),'')
        if old: db.execute(delete(LoginSession).where(LoginSession.token_hash==token_hash(old)))
        db.execute(delete(LoginSession).where(LoginSession.expires<=now))
        token=secrets.token_urlsafe(32)
        db.add(LoginSession(token_hash=token_hash(token),expires=now+TTL,credential_version=credential_version()));db.commit()
    response.set_cookie(cookie_name(),token,max_age=TTL,httponly=True,secure=secure(),samesite='lax',path='/')
    return {'authenticated':True,'username':os.getenv('ADMIN_USERNAME','admin'),'csrf':csrf(token)}
@router.post('/logout')
def logout(request:Request,response:Response):
    token=request.cookies.get(cookie_name(),'')
    with Session() as db:
        db.execute(delete(LoginSession).where(LoginSession.token_hash==token_hash(token)));db.commit()
    response.delete_cookie(cookie_name(),path='/',secure=secure(),httponly=True,samesite='lax')
    return {'authenticated':False}
