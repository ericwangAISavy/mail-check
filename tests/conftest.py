"""Run the standalone smoke checks under pytest without hiding failed checks."""
import pytest


@pytest.fixture
def msgs():
    from tests.test_smoke import normalize_messages
    return normalize_messages()


@pytest.fixture(autouse=True)
def assert_smoke_checks(request, monkeypatch):
    if request.module.__name__ != "tests.test_smoke":
        return
    original = request.module.check

    def checked(label, cond, detail=""):
        original(label, cond, detail)
        assert cond, f"{label}: {detail}"

    monkeypatch.setattr(request.module, "check", checked)
