import os

import pytest

from uploadbot.config import Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    names = (
        "API_ID",
        "API_HASH",
        "BOT_TOKEN",
        "TRANSFER_URL",
        "MAX_FILE_SIZE",
        "MAX_CONCURRENT_TRANSFERS",
        "TRANSFER_TIMEOUT",
        "ALLOWED_USER_IDS",
        "SESSION_PATH",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr("uploadbot.config.load_dotenv", lambda *args: None)
    monkeypatch.setenv("API_ID", "123")
    monkeypatch.setenv("API_HASH", "a" * 32)
    monkeypatch.setenv("BOT_TOKEN", "123:example-test-token")


def test_defaults_and_secret_redaction():
    settings = Settings.from_env()
    assert settings.transfer_url == "https://file2share.us"
    assert settings.max_file_size == 95_000_000
    assert settings.max_transfers == 3
    assert settings.allowed_user_ids == frozenset()
    assert os.environ["BOT_TOKEN"] not in repr(settings)
    assert os.environ["API_HASH"] not in repr(settings)


@pytest.mark.parametrize(
    "name,value",
    [
        ("API_ID", ""),
        ("API_ID", "0"),
        ("API_HASH", ""),
        ("BOT_TOKEN", ""),
        ("MAX_FILE_SIZE", "-1"),
        ("MAX_CONCURRENT_TRANSFERS", "0"),
        ("TRANSFER_TIMEOUT", "abc"),
        ("ALLOWED_USER_IDS", "one"),
        ("ALLOWED_USER_IDS", "-2"),
        ("SESSION_PATH", ""),
        ("TRANSFER_URL", "file:///tmp"),
        ("TRANSFER_URL", "https://host:bad"),
        ("TRANSFER_URL", "https://user:password@host"),
        ("TRANSFER_URL", "https://host?q=1"),
    ],
)
def test_invalid_settings(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        Settings.from_env()


def test_custom_server_and_allowlist(monkeypatch):
    monkeypatch.setenv("TRANSFER_URL", "https://files.example/prefix/")
    monkeypatch.setenv("ALLOWED_USER_IDS", "123, 456")
    monkeypatch.setenv("MAX_FILE_SIZE", "200000000")
    settings = Settings.from_env()
    assert settings.transfer_url == "https://files.example/prefix"
    assert settings.allowed_user_ids == frozenset({123, 456})
    assert settings.max_file_size == 200_000_000


@pytest.mark.parametrize(
    "url", ["https://file2share.us", "https://www.file2share.us", "https://file2share.us."]
)
def test_file2share_limit_is_checked_before_startup(url, monkeypatch):
    monkeypatch.setenv("TRANSFER_URL", url)
    monkeypatch.setenv("MAX_FILE_SIZE", "95000001")
    with pytest.raises(ValueError, match="MAX_FILE_SIZE.*95000000.*File2Share"):
        Settings.from_env()


def test_file2share_limit_can_be_lowered(monkeypatch):
    monkeypatch.setenv("MAX_FILE_SIZE", "1000000")
    assert Settings.from_env().max_file_size == 1_000_000
