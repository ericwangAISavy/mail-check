from typer.testing import CliRunner

from mailcheck import cli, config, db, outlook_auth, secrets


def test_failed_cli_credential_cleanup_preserves_account_and_cached_mail(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'db_path',lambda:tmp_path/'mail.db')
    monkeypatch.setattr(config,'config_path',lambda:tmp_path/'config.toml')
    with db.session() as conn:
        account_id=db.add_account(conn,label='work',email='work@example.test')
        conn.execute("INSERT INTO messages(account_id,message_id,body_text,fetched_at) VALUES(?,?,?,?)",(account_id,'original','cached body',db._now()))
    monkeypatch.setattr(cli.Confirm,'ask',lambda *a,**k:True)
    monkeypatch.setattr(secrets,'delete_account_password',lambda label:None)
    def unavailable(label):raise outlook_auth.OutlookAuthError('Credential store locked')
    monkeypatch.setattr(outlook_auth,'delete_cache',unavailable)
    result=CliRunner().invoke(cli.app,['account','remove','work'])
    assert result.exit_code!=0
    with db.session() as conn:
        assert db.get_account(conn,'work') is not None
        assert conn.execute('SELECT COUNT(*) FROM messages WHERE account_id=?',(account_id,)).fetchone()[0]==1
