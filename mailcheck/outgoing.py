"""TLS-only SMTP for accounts collected over read-only IMAP."""
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid, getaddresses
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from . import db, secrets
from imap_tools.errors import ImapToolsError
from .sources.imap import IMAPSource
from .sources.base import SourceError

SCHEMA="""
CREATE TABLE IF NOT EXISTS mail_outgoing (
 account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 host TEXT NOT NULL,port INTEGER NOT NULL,security TEXT NOT NULL,username TEXT NOT NULL
);
"""
PRESETS={
 'imap.gmail.com':('smtp.gmail.com',465,'ssl'),
 'imap.mail.yahoo.com':('smtp.mail.yahoo.com',465,'ssl'),
 'imap.mail.me.com':('smtp.mail.me.com',587,'starttls'),
 'imap.fastmail.com':('smtp.fastmail.com',465,'ssl'),
}
class Settings(BaseModel):
    host:str=Field(min_length=1,max_length=253)
    port:int=Field(ge=1,le=65535)
    security:Literal['ssl','starttls']='starttls'
    username:str=Field(min_length=1,max_length=320)
    @field_validator('host')
    @classmethod
    def host_only(cls,value):
        value=value.strip()
        if not re.fullmatch(r'[A-Za-z0-9.-]+',value):raise ValueError('Enter an SMTP hostname without a URL or spaces.')
        return value
    @field_validator('username')
    @classmethod
    def username_clean(cls,value):
        if '\r' in value or '\n' in value or not value.strip():raise ValueError('Enter an SMTP username.')
        return value.strip()

class OutgoingError(Exception):pass

def settings(conn,account_id):
    row=conn.execute('SELECT * FROM mail_outgoing WHERE account_id=?',(account_id,)).fetchone()
    return dict(row) if row else None

def public_settings(conn,label):
    account=db.get_account(conn,label)
    if not account or account.provider!='imap':raise OutgoingError('Choose an IMAP-connected account.')
    stored=settings(conn,account.id)
    host,port,security=PRESETS.get(account.imap_host.lower(),('',587,'starttls'))
    return {'configured':bool(stored),'host':stored['host'] if stored else host,'port':stored['port'] if stored else port,
            'security':stored['security'] if stored else security,'username':stored['username'] if stored else account.email}

def open_smtp(label,values):
    try:
        password=secrets.get_account_password(label)
        if values['security']=='ssl':
            server=smtplib.SMTP_SSL(values['host'],values['port'],timeout=30,context=ssl.create_default_context())
        else:
            server=smtplib.SMTP(values['host'],values['port'],timeout=30)
            try:server.starttls(context=ssl.create_default_context())
            except Exception:
                server.close();raise
        try:server.login(values['username'],password)
        except Exception:
            server.close();raise
        return server
    except secrets.SecretError as exc:raise OutgoingError('The account app password is unavailable. Reconnect the mailbox.') from exc
    except smtplib.SMTPAuthenticationError as exc:raise OutgoingError('SMTP sign-in failed. Check the username and account app password.') from exc
    except (smtplib.SMTPException,OSError) as exc:raise OutgoingError('Could not connect securely to the outgoing mail server. Check the SMTP hostname, port and TLS setting.') from exc

def save_settings(conn,label,body):
    account=db.get_account(conn,label)
    if not account or account.provider!='imap':raise OutgoingError('Choose an IMAP-connected account.')
    server=open_smtp(label,body.model_dump())
    try:server.quit()
    except (OSError,smtplib.SMTPException):pass
    finally:
        try:server.close()
        except (OSError,smtplib.SMTPException):pass
    conn.execute('''INSERT INTO mail_outgoing VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
        host=excluded.host,port=excluded.port,security=excluded.security,username=excluded.username''',
        (account.id,body.host,body.port,body.security,body.username))

def metadata(row):
    if not re.fullmatch(r'\d+',row.get('uid') or ''):raise OutgoingError('The original message has no valid IMAP identifier. Refresh this mailbox.')
    try:
        source=IMAPSource(host=row['imap_host'],port=row['imap_port'],username=row['account_email'],
            password=secrets.get_account_password(row['account_label']),use_ssl=bool(row['use_ssl']),folder=row['folder'])
        box=source._open()
        try:
            item=next(iter(box.fetch(f"UID {row['uid']}",headers_only=True,mark_seen=False,limit=1)),None)
            if item is None:raise OutgoingError('The original message was not found in this mailbox. Refresh mail before replying.')
            headers={k.lower():v for k,v in item.headers.items()}
        finally:
            try:box.logout()
            except Exception:pass
    except (SourceError,secrets.SecretError,ImapToolsError,OSError) as exc:raise OutgoingError('Could not read reply headers from this mailbox. Check the account connection.') from exc
    def values(name):
        value=headers.get(name,[])
        return [value] if isinstance(value,str) else value
    mid=''.join(values('message-id')).strip()
    if mid!=row['message_id'] and not row['message_id'].startswith('<no-id-'):
        raise OutgoingError('The original message identifier changed. Refresh mail before replying.')
    def recipients(name):return [{'emailAddress':{'address':address}} for _,address in getaddresses(values(name)) if address]
    return {'id':row['uid'],'subject':row['subject'],'from':{'emailAddress':{'address':row['from_addr']}},
            'replyTo':recipients('reply-to'),'toRecipients':recipients('to'),'ccRecipients':recipients('cc'),
            'references':values('references'),'internetMessageId':mid}

def message(row,item,envelope,body,operation):
    msg=EmailMessage()
    msg['From']=row['account_email']
    msg['To']=', '.join(envelope['to'])
    if envelope['cc']:msg['Cc']=', '.join(envelope['cc'])
    msg['Subject']=' '.join(envelope['subject'].splitlines())
    msg['Date']=format_datetime(datetime.now(timezone.utc))
    msg['Message-ID']=make_msgid(idstring=operation)
    original=item.get('internetMessageId')
    if original and ('\r' in original or '\n' in original):raise OutgoingError('The original message has invalid reply headers.')
    if original:
        msg['In-Reply-To']=original
        references=' '.join(' '.join(item.get('references') or []).split())
        msg['References']=(references+' '+original).strip()
    msg.set_content(body)
    return msg
