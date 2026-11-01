"""Explicit Outlook and SMTP replies with a durable, account-scoped delivery ledger."""
from __future__ import annotations
import json
import smtplib
from datetime import datetime, timezone
from urllib.parse import quote
from uuid import UUID
import httpx
from pydantic import BaseModel, Field, field_validator
from typing import Literal
from . import config, db, outgoing
from .outlook_auth import acquire_token, OutlookAuthError

SEND_SCOPES = ['Mail.Read','Mail.Send']
GRAPH = 'https://graph.microsoft.com/v1.0'
SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_replies (
 operation TEXT PRIMARY KEY,message_pk INTEGER NOT NULL,account_id INTEGER NOT NULL,
 original_message_id TEXT NOT NULL DEFAULT '',body TEXT NOT NULL,mode TEXT NOT NULL,mark_done INTEGER NOT NULL,
 status TEXT NOT NULL,created_at TEXT NOT NULL,sent_at TEXT,
 recipients TEXT NOT NULL DEFAULT '{}',error TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_mail_replies_message ON mail_replies(message_pk,created_at);
"""

class ReplyBody(BaseModel):
    operation: UUID
    body: str = Field(min_length=1,max_length=30000)
    mode: Literal['reply','reply_all'] = 'reply'
    mark_done: bool = False

    @field_validator('body')
    @classmethod
    def not_empty(cls,value):
        if not value.strip(): raise ValueError('Write a reply before sending.')
        return value

class ReplyError(Exception):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status

def client_id():
    return config.load().outlook.client_id

def graph_client(token):
    return httpx.Client(timeout=45,headers={'Authorization':f'Bearer {token}','Accept':'application/json'})

def account_message(conn,pk):
    row=conn.execute('''SELECT m.*,a.label AS account_label,a.email AS account_email,
        a.provider,a.enabled,a.imap_host,a.imap_port,a.use_ssl FROM messages m JOIN accounts a ON a.id=m.account_id WHERE m.id=?''',(pk,)).fetchone()
    if not row: raise ReplyError('No such message.',404)
    if row['provider'] not in ('outlook','imap'): raise ReplyError('This account does not support replies.')
    if not row['enabled']: raise ReplyError('Enable this account before sending replies.')
    if row['provider']=='outlook' and not client_id(): raise ReplyError('Configure Microsoft sign-in before sending replies.')
    return dict(row)

def token_for(row):
    try: return acquire_token(row['account_label'],client_id(),scopes=SEND_SCOPES)
    except OutlookAuthError as exc:
        raise ReplyError('Reconnect this Outlook account to grant Mail.Send permission for replies.',409) from exc

def metadata(client,row):
    fields='id,internetMessageId,subject,from,replyTo,toRecipients,ccRecipients'
    try:
        response=client.get(f"{GRAPH}/me/messages/{quote(row['uid'] or '',safe='')}",params={'$select':fields}) if row['uid'] else None
        if response is None or response.status_code==404:
            original=row['message_id'].replace("'","''")
            response=client.get(f'{GRAPH}/me/messages',params={'$filter':f"internetMessageId eq '{original}'",'$select':fields,'$top':2})
            check_response(response)
            matches=response.json().get('value',[])
            if len(matches)!=1: raise ReplyError('The original message could not be found in this mailbox. Refresh mail and try again.',404)
            item=matches[0]
        else:
            check_response(response)
            item=response.json()
    except (httpx.TransportError,ValueError) as exc:
        raise ReplyError('Could not load the original message from Microsoft. Your reply has not been sent.',502) from exc
    if not item.get('id'): raise ReplyError('Microsoft returned no message identifier.',502)
    if not row['message_id'].startswith('<graph-') and item.get('internetMessageId')!=row['message_id']:
        raise ReplyError('The stored message no longer matches the mailbox message. Refresh mail before replying.',409)
    return item

def check_response(response):
    if response.status_code in (401,403): raise ReplyError('Reconnect this Outlook account to grant permission for replies.',409)
    if response.status_code>=400: raise ReplyError(f'Microsoft rejected the request (HTTP {response.status_code}). No reply was sent.',502)

def addresses(values):
    return list(dict.fromkeys(a['emailAddress']['address'] for a in values or [] if (a.get('emailAddress') or {}).get('address')))

def envelope(row,item,mode):
    to=addresses(item.get('replyTo')) or addresses([item.get('from') or {}])
    cc=[]
    if mode=='reply_all':
        to+=addresses(item.get('toRecipients'))
        cc=addresses(item.get('ccRecipients'))
    own=row['account_email'].casefold()
    to=list({a.casefold():a for a in to if a.casefold()!=own}.values())
    cc=list({a.casefold():a for a in cc if a.casefold()!=own and a.casefold() not in {b.casefold() for b in to}}.values())
    subject=item.get('subject') or '(no subject)'
    return {'from':row['account_email'],'to':to,'cc':cc,'subject':subject if subject.lower().startswith('re:') else 'Re: '+subject}

def context(conn,pk,mode='reply'):
    row=account_message(conn,pk)
    if row['provider']=='imap':
        if not outgoing.settings(conn,row['account_id']):raise ReplyError('Configure outgoing mail for this account before replying.',409)
        try:item=outgoing.metadata(row)
        except outgoing.OutgoingError as exc:raise ReplyError(str(exc),409) from exc
    else:
        with graph_client(token_for(row)) as client:item=metadata(client,row)
    return envelope(row,item,mode)

def history(conn,pk):
    return [dict(r) for r in conn.execute("""SELECT r.operation,r.body,r.mode,r.status,r.created_at,r.sent_at,r.recipients,r.error FROM mail_replies r JOIN messages m ON m.id=r.message_pk AND m.account_id=r.account_id AND m.message_id=r.original_message_id WHERE m.id=? ORDER BY r.created_at""",(pk,))]

def send(pk,body):
    operation=str(body.operation)
    with db.session() as conn:
        row=account_message(conn,pk)
        conn.execute('BEGIN IMMEDIATE')
        previous=conn.execute('SELECT * FROM mail_replies WHERE operation=?',(operation,)).fetchone()
        if previous:
            if (previous['message_pk'],previous['account_id'],previous['original_message_id'],previous['body'],previous['mode'],bool(previous['mark_done']))!=(pk,row['account_id'],row['message_id'],body.body,body.mode,body.mark_done):
                raise ReplyError('This send request has already been used for another reply.',409)
            if previous['status']=='sent': return {'ok':True,'sent_at':previous['sent_at'],'done':bool(previous['mark_done']) and not bool(previous['error']),'warning':previous['error']}
            if previous['status'] in ('preparing','sending','unknown'):
                raise ReplyError('Delivery is not confirmed. Do not resend this reply until its delivery is verified; The mail server may have accepted it.',409)
            conn.execute("UPDATE mail_replies SET status='preparing',error='' WHERE operation=?",(operation,))
        else:
            conn.execute("INSERT INTO mail_replies(operation,message_pk,account_id,original_message_id,body,mode,mark_done,status,created_at) VALUES(?,?,?,?,?,?,?,'preparing',?)",
                (operation,pk,row['account_id'],row['message_id'],body.body,body.mode,int(body.mark_done),datetime.now(timezone.utc).isoformat()))
    attempted=False
    try:
        warning=''
        if row['provider']=='imap':
            with db.session() as conn: smtp_settings=outgoing.settings(conn,row['account_id'])
            if not smtp_settings:raise ReplyError('Configure outgoing mail for this account before replying.',409)
            item=outgoing.metadata(row)
            recipients=envelope(row,item,body.mode)
            if not recipients['to']:raise ReplyError('No reply recipient was found for this message.')
            mail=outgoing.message(row,item,recipients,body.body,operation)
            smtp=outgoing.open_smtp(row['account_label'],smtp_settings)
            try:
                with db.session() as conn:conn.execute("UPDATE mail_replies SET status='sending',recipients=? WHERE operation=?",(json.dumps(recipients),operation))
                attempted=True
                try:
                    refused=smtp.send_message(mail,from_addr=row['account_email'],to_addrs=recipients['to']+recipients['cc'])
                except (smtplib.SMTPRecipientsRefused,smtplib.SMTPDataError) as exc:
                    attempted=False
                    raise ReplyError('The outgoing server rejected this reply. Check the recipients and try again.',502) from exc
                if refused:warning='The server accepted the reply, but some recipients were rejected: '+', '.join(refused)
            finally:
                # Closing a connection must not turn an accepted send into a retry.
                try:smtp.close()
                except (OSError,smtplib.SMTPException):pass
        else:
            with graph_client(token_for(row)) as client:
                item=metadata(client,row)
                recipients=envelope(row,item,body.mode)
                if not recipients['to']: raise ReplyError('No reply recipient was found for this message.')
                with db.session() as conn:
                    conn.execute("UPDATE mail_replies SET status='sending',recipients=? WHERE operation=?",(json.dumps(recipients),operation))
                attempted=True
                # Never retry a send: a timed-out POST can still have been accepted.
                action='replyAll' if body.mode=='reply_all' else 'reply'
                response=client.post(f"{GRAPH}/me/messages/{quote(item['id'],safe='')}/{action}",json={'message':{'body':{'contentType':'Text','content':body.body}}})
                if response.status_code!=202:
                    if response.status_code>=500: raise httpx.ReadError('Microsoft did not confirm acceptance.')
                    attempted=False
                    check_response(response)
                    raise ReplyError(f'Microsoft did not accept the reply (HTTP {response.status_code}).',502)
        sent_at=datetime.now(timezone.utc).isoformat()
        with db.session() as conn:
            conn.execute("UPDATE mail_replies SET status='sent',sent_at=?,error=? WHERE operation=?",(sent_at,warning,operation))
            if body.mark_done and not warning: db.set_handled(conn,pk,True)
        return {'ok':True,'sent_at':sent_at,'done':body.mark_done and not warning,'warning':warning}
    except (ReplyError,httpx.TransportError,outgoing.OutgoingError,smtplib.SMTPException,OSError) as exc:
        error=('Delivery is not confirmed. The mail server may have accepted your reply. Do not resend until delivery is verified.' if attempted else str(exc))
        with db.session() as conn:
            conn.execute('UPDATE mail_replies SET status=?,error=? WHERE operation=?',('unknown' if attempted else 'failed',error,operation))
        raise ReplyError(error,409 if attempted else getattr(exc,'status',502)) from exc
