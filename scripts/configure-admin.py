"""Run interactively on your own computer/server. Never paste passwords in chat."""
import getpass,hashlib,secrets,base64,re,sys
from pathlib import Path

def main():
    path=Path(sys.argv[1] if len(sys.argv)>1 else '.env')
    username=input('Administrator username [admin]: ').strip() or 'admin'
    if not re.fullmatch(r'[A-Za-z0-9_.@-]{1,100}',username): raise SystemExit('Use letters, numbers, dot, underscore, @ or hyphen for username.')
    password=getpass.getpass('New password (12 or more characters): ')
    if len(password)<12 or len(password)>256: raise SystemExit('Password must be 12–256 characters.')
    if password!=getpass.getpass('Confirm password: '): raise SystemExit('Passwords do not match.')
    salt=secrets.token_bytes(16)
    key=hashlib.scrypt(password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32,maxmem=64*1024*1024)
    values={'AUTH_REQUIRED':'true','ADMIN_USERNAME':username,'ADMIN_PASSWORD_HASH':'scrypt.'+base64.urlsafe_b64encode(salt+key).decode()}
    old=path.read_text('utf-8') if path.exists() else ''
    if not re.search(r'^DB_PASSWORD=.+$',old,re.M): values['DB_PASSWORD']=secrets.token_urlsafe(32)
    lines=old.splitlines()
    for name,value in values.items():
        lines=[line for line in lines if not line.startswith(name+'=')];lines.append(name+'='+value)
    path.write_text('\n'.join(lines)+'\n','utf-8')
    try: path.chmod(0o600)
    except OSError: pass
    print('Administrator configured. No plaintext password was saved. Existing sessions are revoked after restarting API/worker with this file.')
if __name__=='__main__': main()
