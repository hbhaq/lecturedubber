import time
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app import auth
from app.db import Session, LoginSession
from sqlalchemy import select

@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv('AUTH_REQUIRED','true')
    monkeypatch.setenv('ADMIN_USERNAME','teacher')
    monkeypatch.setenv('ADMIN_PASSWORD_HASH',auth.password_hash('test-only-password-123'))
    monkeypatch.delenv('PUBLIC_ORIGIN',raising=False)

def signin(client):
    r=client.post('/auth/login',json={'username':'teacher','password':'test-only-password-123'},headers={'Origin':'http://localhost:3000'})
    assert r.status_code==200,r.text
    return {'Origin':'http://localhost:3000','X-CSRF-Token':r.json()['csrf']}

def test_private_routes_and_cookie_flags(enabled):
    with TestClient(app) as c:
        assert c.get('/health').status_code==200
        assert c.get('/auth/session').json()['authenticated'] is False
        for path in ('/lectures','/lectures/unknown/assets/source','/docs','/openapi.json'):
            assert c.get(path).status_code==401
        headers=signin(c)
        assert c.get('/lectures').status_code==200
        r=c.post('/lectures',json={'title':'Private lecture'},headers=headers)
        assert r.status_code==200
        assert c.get('/auth/session').json()['authenticated'] is True
        # Session database holds only the token hash, never the cookie secret.
        with Session() as db:
            row=db.scalar(select(LoginSession));assert row.token_hash!=c.cookies.get(auth.cookie_name())

def test_csrf_logout_and_expiration(enabled):
    with TestClient(app) as c:
        headers=signin(c)
        assert c.post('/lectures',json={'title':'x'}).status_code==403
        assert c.post('/lectures',json={'title':'x'},headers={**headers,'Origin':'https://evil.example'}).status_code==403
        assert c.post('/auth/logout',headers=headers).status_code==200
        assert c.get('/lectures').status_code==401
        signin(c)
        with Session() as db:
            row=db.scalar(select(LoginSession));row.expires=time.time()-1;db.commit()
        assert c.get('/lectures').status_code==401

def test_failed_logins_are_throttled_and_origin_checked(enabled):
    with TestClient(app) as c:
        creds={'username':'teacher','password':'incorrect'}
        assert c.post('/auth/login',json=creds).status_code==403
        for _ in range(5):
            assert c.post('/auth/login',json=creds,headers={'Origin':'http://localhost:3000'}).status_code==401
        r=c.post('/auth/login',json=creds,headers={'Origin':'http://localhost:3000'})
        assert r.status_code==429 and r.headers['Retry-After']=='60'

def test_password_rotation_revokes_existing_sessions(enabled,monkeypatch):
    with TestClient(app) as c:
        signin(c)
        monkeypatch.setenv('ADMIN_PASSWORD_HASH',auth.password_hash('new-test-password-123'))
        assert c.get('/lectures').status_code==401

def test_public_settings_fail_closed_and_secure_cookies(enabled,monkeypatch):
    monkeypatch.setenv('PUBLIC_ORIGIN','http://lectures.example.com')
    with pytest.raises(RuntimeError): auth.validate_settings()
    monkeypatch.setenv('PUBLIC_ORIGIN','https://lectures.example.com')
    monkeypatch.setenv('AUTH_REQUIRED','false')
    with pytest.raises(RuntimeError): auth.validate_settings()
    monkeypatch.setenv('AUTH_REQUIRED','true');auth.validate_settings()
    with TestClient(app,base_url='https://localhost') as c:
        r=c.post('/auth/login',json={'username':'teacher','password':'test-only-password-123'},headers={'Origin':'https://lectures.example.com'})
        assert r.status_code==200
        cookie=r.headers['set-cookie']
        assert '__Host-lecture_session=' in cookie and 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie
        assert c.get('/lectures').status_code==200

def test_missing_hash_prevents_startup(monkeypatch):
    monkeypatch.setenv('AUTH_REQUIRED','true');monkeypatch.delenv('ADMIN_PASSWORD_HASH',raising=False)
    with pytest.raises(RuntimeError): auth.validate_settings()

def test_password_hash_is_salted_and_verified():
    a=auth.password_hash('test-phrase-123');b=auth.password_hash('test-phrase-123')
    assert a!=b and auth.verify('test-phrase-123',a)
    assert not auth.verify('wrong',a) and not auth.verify('x','malformed')
