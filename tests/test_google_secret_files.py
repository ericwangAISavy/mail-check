"""Windows Google OAuth secrets live in DPAPI files, not Credential Manager chunks."""
import json

import keyring
import pytest

from mailcheck import dpapi, google_oauth as google, secret_files
from mailcheck.google_sheets import GoogleError
from mailcheck.workspaces import credential_namespace

TOKENS = json.dumps({"refresh_token": "R" * 2500, "access_token": "A" * 1500})


class Store:
    def __init__(self):
        self.values = {}
        self.full = False
        self.broken = False

    def get(self, service, key):
        if self.broken:
            raise keyring.errors.KeyringError("locked")
        return self.values.get(key)

    def set(self, service, key, value):
        if self.full:
            raise OSError(8, "CredWrite", "Not enough memory resources are available to process this command")
        self.values[key] = value

    def delete(self, service, key):
        if key not in self.values:
            raise keyring.errors.PasswordDeleteError("missing")
        del self.values[key]


@pytest.fixture
def store(monkeypatch):
    fake = Store()
    monkeypatch.setattr(google.keyring, "get_password", fake.get)
    monkeypatch.setattr(google.keyring, "set_password", fake.set)
    monkeypatch.setattr(google.keyring, "delete_password", fake.delete)
    monkeypatch.setattr(secret_files, "enabled", lambda: True)
    if not dpapi.available():
        monkeypatch.setattr(dpapi, "protect", lambda data, entropy: entropy + b"|" + data[::-1])

        def unprotect(data, entropy):
            if not data.startswith(entropy + b"|"):
                raise OSError("wrong entropy")
            return data[len(entropy) + 1:][::-1]
        monkeypatch.setattr(dpapi, "unprotect", unprotect)
    return fake


def namespaced(key):
    return credential_namespace() + key


def test_generation_chunks_migrate_to_a_file_and_free_credentials(store):
    key = namespaced("tokens")
    chunks = [TOKENS[i:i + 1000] for i in range(0, len(TOKENS), 1000)]
    generation = "a" * 32
    for i, chunk in enumerate(chunks):
        store.values[f"{key}.{generation}.{i}"] = chunk
    store.values[key + ".active"] = json.dumps({"generation": generation, "count": len(chunks)})
    assert google.read_secret("tokens") == TOKENS
    assert store.values == {}
    assert google.read_secret("tokens") == TOKENS


def test_legacy_count_chunks_migrate_too(store):
    key = namespaced("config")
    store.values.update({key + ".count": "2", key + ".0": '{"client_id":', key + ".1": '"abc"}'})
    assert google.read_secret("config") == '{"client_id":"abc"}'
    assert store.values == {}


def test_saving_needs_no_free_credential_manager_space(store):
    store.full = True
    google.write_secret("tokens", TOKENS)
    google.write_secret("config", '{"client_id":"abc"}')
    assert store.values == {}
    assert google.read_secret("tokens") == TOKENS
    assert google.read_secret("config") == '{"client_id":"abc"}'
    files = list(secret_files.folder("google-credentials").iterdir())
    assert len(files) == 2 and not any("tokens" in f.name or "config" in f.name for f in files)


def test_disconnect_and_missing_secrets_read_as_empty(store):
    assert google.read_secret("tokens") is None
    google.write_secret("tokens", TOKENS)
    google.write_secret("tokens", "{}")
    assert google.read_secret("tokens") == "{}"
    google.write_secret("tokens", "")
    assert google.read_secret("tokens") is None


def test_unreadable_file_means_reconnect_and_copied_files_do_not_decrypt(store):
    google.write_secret("tokens", TOKENS)
    source = google._file(namespaced("tokens"))
    google._file(namespaced("config")).write_bytes(source.read_bytes())
    assert google.read_secret("config") is None
    source.write_bytes(b"garbage")
    assert google.read_secret("tokens") is None


def test_unavailable_store_without_a_file_is_a_recoverable_error(store):
    store.broken = True
    with pytest.raises(GoogleError, match="credential store"):
        google.read_secret("tokens")
    google.write_secret("tokens", TOKENS)  # saving needs only the file
    assert google.read_secret("tokens") == TOKENS


def test_failed_migration_keeps_using_the_old_entries(store, monkeypatch):
    key = namespaced("tokens")
    store.values.update({key + ".count": "1", key + ".0": TOKENS})

    def unwritable(*args):
        raise PermissionError("read-only")
    monkeypatch.setattr(secret_files, "write", unwritable)
    assert google.read_secret("tokens") == TOKENS
    assert store.values
