"""Windows Outlook token caches live in DPAPI files, not Credential Manager chunks."""
import os

import keyring
import pytest

from mailcheck import dpapi, outlook_auth as auth

CACHE = '{"RefreshToken":{"k":{"secret":"' + "R" * 5000 + '"}}}'


class FullCredentialStore:
    """In-memory keyring that can refuse new entries like a full Credential Manager."""

    def __init__(self):
        self.values = {}
        self.full = False
        self.fail_delete = False

    def get(self, service, key):
        return self.values.get(key)

    def set(self, service, key, value):
        if self.full:
            raise OSError(8, "CredWrite", "Not enough memory resources are available to process this command")
        self.values[key] = value

    def delete(self, service, key):
        if self.fail_delete:
            raise keyring.errors.KeyringError("locked")
        if key not in self.values:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.values[key]


@pytest.fixture
def store(monkeypatch):
    fake = FullCredentialStore()
    monkeypatch.setattr(auth.keyring, "get_password", fake.get)
    monkeypatch.setattr(auth.keyring, "set_password", fake.set)
    monkeypatch.setattr(auth.keyring, "delete_password", fake.delete)
    monkeypatch.setattr(auth, "_file_store", lambda: True)
    if not dpapi.available():  # portable stand-in: reversible, and bound to its entropy
        def protect(data, entropy):
            return entropy + b"|" + bytes(b ^ 0x5A for b in data)

        def unprotect(data, entropy):
            if not data.startswith(entropy + b"|"):
                raise OSError("wrong entropy")
            return bytes(b ^ 0x5A for b in data[len(entropy) + 1:])
        monkeypatch.setattr(auth.dpapi, "protect", protect)
        monkeypatch.setattr(auth.dpapi, "unprotect", unprotect)
    return fake


def put_chunked(store, label, blob):
    chunks = [blob[i:i + auth.CHUNK_CHARS] for i in range(0, len(blob), auth.CHUNK_CHARS)]
    for i, piece in enumerate(chunks):
        store.values[auth._chunk_key(label, i)] = piece
    store.values[auth._cache_key(label)] = f"chunks:{len(chunks)}"


def test_existing_chunked_cache_migrates_to_one_file_and_frees_credentials(store):
    put_chunked(store, "work", CACHE)
    assert len(store.values) > 2
    assert auth._read_blob("work") == CACHE
    assert store.values == {}
    assert auth._token_file("work").is_file()
    assert auth._read_blob("work") == CACHE  # now served from the file


def test_saving_needs_no_free_credential_manager_space(store):
    store.full = True
    auth._write_blob("work", CACHE)
    assert store.values == {}
    assert auth._read_blob("work") == CACHE
    assert auth.has_cache("work")
    assert [p.name for p in auth._token_dir().iterdir()] == [auth._token_file("work").name]


def test_saving_frees_chunks_left_by_an_earlier_partial_migration(store):
    put_chunked(store, "work", "old" * 2000)
    auth._write_blob("work", CACHE)
    assert store.values == {}
    assert auth._read_blob("work") == CACHE


def test_migration_keeps_the_account_signed_in_when_old_entries_cannot_be_deleted(store):
    put_chunked(store, "work", CACHE)
    store.fail_delete = True
    assert auth._read_blob("work") == CACHE
    assert auth._token_file("work").is_file()
    store.fail_delete = False
    auth._write_blob("work", CACHE)  # the next save retries the cleanup
    assert store.values == {}


def test_corrupt_or_copied_files_mean_reconnect_not_a_crash(store):
    auth._write_blob("work", CACHE)
    auth._token_dir().joinpath(auth._token_file("home").name).write_bytes(auth._token_file("work").read_bytes())
    assert auth._read_blob("home") == ""  # encrypted for another account
    auth._token_file("work").write_bytes(b"not a token file")
    assert auth._read_blob("work") == ""
    assert auth.load_cache("work").serialize() in ("{}", "")


def test_files_are_not_plaintext_and_differ_per_account(store):
    auth._write_blob("work", CACHE)
    auth._write_blob("home", CACHE)
    raw = auth._token_file("work").read_bytes()
    assert raw.startswith(auth.TOKEN_FILE_MAGIC)
    assert auth._token_file("work") != auth._token_file("home")
    assert "work" not in auth._token_file("work").name
    if dpapi.available():
        assert b"RRRRRRRR" not in raw


def test_failed_save_keeps_the_previous_cache_and_leaves_no_temporary_file(store, monkeypatch):
    auth._write_blob("work", CACHE)

    def interrupted(source, target):
        raise OSError("disk full")
    monkeypatch.setattr(auth.os, "replace", interrupted)
    with pytest.raises(auth.OutlookAuthError):
        auth._write_blob("work", "replacement")
    monkeypatch.setattr(auth.os, "replace", os.replace)
    assert auth._read_blob("work") == CACHE
    assert [p.name for p in auth._token_dir().iterdir()] == [auth._token_file("work").name]


def test_account_removal_deletes_the_file_and_any_old_entries(store):
    auth._write_blob("work", CACHE)
    put_chunked(store, "work", "stale")
    auth.delete_cache("work")
    assert not auth._token_file("work").exists()
    assert store.values == {}
    assert not auth.has_cache("work")
    assert auth._read_blob("work") == ""


@pytest.mark.skipif(not dpapi.available(), reason="Windows DPAPI only")
def test_real_dpapi_round_trip_is_bound_to_its_entropy():
    secret = CACHE.encode()
    protected = dpapi.protect(secret, b"work")
    assert secret not in protected
    assert dpapi.unprotect(protected, b"work") == secret
    with pytest.raises(OSError):
        dpapi.unprotect(protected, b"home")


def test_failed_removal_keeps_the_account_signed_in(store):
    auth._write_blob("work", CACHE)
    store.fail_delete = True
    store.values[auth._cache_key("work")] = "chunks:1"  # a locked store refuses this delete
    with pytest.raises(auth.OutlookAuthError):
        auth.delete_cache("work")
    assert auth._read_blob("work") == CACHE


def test_failed_migration_keeps_using_the_old_entries(store, monkeypatch):
    put_chunked(store, "work", CACHE)

    def unwritable(label, blob):
        raise PermissionError("config folder is read-only")
    monkeypatch.setattr(auth, "_write_file_blob", unwritable)
    assert auth._read_blob("work") == CACHE
    assert store.values  # nothing freed until the file is safely written
    monkeypatch.undo()


def test_save_retries_a_briefly_locked_token_file(store, monkeypatch):
    calls = []
    real_replace = os.replace

    def flaky(source, target):
        calls.append(target)
        if len(calls) < 3:
            raise PermissionError("sharing violation")
        real_replace(source, target)
    monkeypatch.setattr(auth.os, "replace", flaky)
    monkeypatch.setattr(auth.time, "sleep", lambda seconds: None)
    auth._write_blob("work", CACHE)
    assert len(calls) == 3
    monkeypatch.setattr(auth.os, "replace", os.replace)
    assert auth._read_blob("work") == CACHE


def test_cleanup_frees_chunks_after_a_gap_from_a_torn_write(store):
    put_chunked(store, "work", "x" * (auth.CHUNK_CHARS * 4))
    del store.values[auth._chunk_key("work", 1)]
    auth._write_blob("work", CACHE)
    assert store.values == {}
