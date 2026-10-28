"""Server-only Google OAuth credentials, PKCE, and browser-bound single-use state."""
import base64
import hashlib
import json
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit
import httpx
import keyring
from .google_sheets import GoogleError

SERVICE='mail-check-google'
_credential_lock=threading.RLock()

def _location(key):
    """The active pointer switches only after every new chunk exists."""
    pointer=keyring.get_password(SERVICE,key+'.active')
    if pointer:
        metadata=json.loads(pointer)
        generation=metadata['generation']
        if not isinstance(generation,str) or len(generation)!=32 or any(c not in '0123456789abcdef' for c in generation):
            raise ValueError('Invalid credential generation')
        prefix=key+'.'+generation
        count=int(metadata['count'])
    else:
        prefix=key
        count=int(keyring.get_password(SERVICE,key+'.count') or '0')
    if not 0<=count<=64: raise ValueError('Invalid credential chunk count')
    return prefix,count

def read_secret(key):
    from .workspaces import credential_namespace
    key=credential_namespace()+key
    with _credential_lock:
        try:
            prefix,count=_location(key)
            chunks=[keyring.get_password(SERVICE,f'{prefix}.{i}') for i in range(count)]
            if any(chunk is None for chunk in chunks): raise ValueError('Incomplete credential bundle')
            return ''.join(chunks) or None
        except (keyring.errors.KeyringError,OSError,ValueError,KeyError,TypeError) as exc:
            raise GoogleError('The operating system credential store is unavailable.') from exc

def write_secret(key,value):
    from .workspaces import credential_namespace
    key=credential_namespace()+key
    with _credential_lock:
        try:
            old_prefix,old_count=_location(key)
            chunks=[value[i:i+1000] for i in range(0,len(value),1000)]
            if len(chunks)>64: raise ValueError('Credential bundle is too large')
            generation=secrets.token_hex(16)
            prefix=key+'.'+generation
            for i,chunk in enumerate(chunks):
                name=f'{prefix}.{i}'
                keyring.set_password(SERVICE,name,chunk)
            keyring.set_password(SERVICE,key+'.active',json.dumps({'generation':generation,'count':len(chunks)}))
        except (keyring.errors.KeyringError,OSError,ValueError,KeyError,TypeError) as exc:
            # The active generation remains usable if staging fails. A failed
            # pointer update can be ambiguous, so retain complete staged data.
            raise GoogleError('The operating system credential store is unavailable.') from exc
        # Cleanup cannot turn a committed replacement into a reported failure.
        for i in range(old_count):
            try: keyring.delete_password(SERVICE,f'{old_prefix}.{i}')
            except (keyring.errors.KeyringError,OSError): pass

class GoogleConnection:
    def __init__(self,*,client=None):
        self.client=client or httpx.Client(timeout=30)
        self.pending={};self.lock=threading.RLock()
    def _read(self,key): return json.loads(read_secret(key) or '{}')
    def setup(self,client_id,client_secret,redirect_uri):
        url=urlsplit(redirect_uri)
        if url.scheme not in ('https','http') or (url.scheme=='http' and url.hostname not in ('localhost','127.0.0.1')) or url.path!='/api/google/callback' or url.query or url.fragment:
            raise ValueError('Use your app HTTPS address followed by /api/google/callback (HTTP is allowed on localhost).')
        write_secret('config',json.dumps({'client_id':client_id,'client_secret':client_secret,'redirect_uri':redirect_uri}))
    def status(self):
        cfg=self._read('config');tokens=self._read('tokens')
        return {'configured':bool(cfg.get('client_id')),'connected':bool(tokens.get('refresh_token')),'client_id':cfg.get('client_id',''),'redirect_uri':cfg.get('redirect_uri','')}
    def begin(self):
        cfg=self._read('config')
        if not cfg: raise ValueError('Configure Google OAuth first.')
        state=secrets.token_urlsafe(32);cookie=secrets.token_urlsafe(32);verifier=secrets.token_urlsafe(64)
        with self.lock:
            self.pending={k:v for k,v in self.pending.items() if v['expires']>time.time()}
            self.pending[state]={'cookie':cookie,'verifier':verifier,'expires':time.time()+600,'config':cfg}
        query={**cfg,'response_type':'code','scope':'https://www.googleapis.com/auth/spreadsheets','access_type':'offline','prompt':'consent','state':state,'code_challenge_method':'S256','code_challenge':base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()}
        query.pop('client_secret')
        return {'state':state,'cookie':cookie,'url':'https://accounts.google.com/o/oauth2/v2/auth?'+urlencode(query)}
    def complete(self,state,code,cookie):
        with self.lock: pending=self.pending.pop(state,None)
        if not pending or pending['expires']<time.time() or not secrets.compare_digest(pending['cookie'],cookie or ''): raise ValueError('Google connection expired or belongs to another browser. Start again.')
        tokens=self._exchange({**pending['config'],'grant_type':'authorization_code','code':code,'code_verifier':pending['verifier']})
        if not tokens.get('refresh_token'): raise GoogleError('Google did not grant offline access. Reconnect with consent.')
        tokens['oauth_config']=pending['config']
        write_secret('tokens',json.dumps(tokens))
    def _exchange(self,data):
        try: response=self.client.post('https://oauth2.googleapis.com/token',data=data)
        except httpx.HTTPError as exc: raise GoogleError('Google could not be reached.') from exc
        if response.is_error: raise GoogleError('Google authorization failed. Reconnect your account.')
        token=response.json();token['expires_at']=time.time()+token.get('expires_in',3600)-60
        return token
    def token(self):
        with self.lock:
            tokens=self._read('tokens')
            if not tokens.get('refresh_token'): raise GoogleError('Connect Google first.')
            if tokens.get('expires_at',0)<time.time():
                refreshed=self._exchange({**tokens.get('oauth_config',self._read('config')),'grant_type':'refresh_token','refresh_token':tokens['refresh_token']})
                tokens.update(refreshed);write_secret('tokens',json.dumps(tokens))
            return tokens['access_token']
    def disconnect(self): write_secret('tokens','{}')
