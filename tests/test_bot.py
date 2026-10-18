import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import errors, types

from config import Settings
from plugins.bot import UploadBot, public_link
from utils.transfer import TransferError


def event(text="", file=None, user_id=1):
    return SimpleNamespace(
        is_private=True,
        sender_id=user_id,
        raw_text=text,
        id=1,
        message=SimpleNamespace(
            file=file,
            media=types.MessageMediaDocument() if file else None,
        ),
        reply=AsyncMock(),
        get_input_chat=AsyncMock(return_value="chat"),
    )


def bot(**settings):
    config = replace(Settings(123, "0" * 32, "123:test"), **settings)
    return UploadBot(SimpleNamespace(send_file=AsyncMock()), None, config)


async def test_commands_do_not_download():
    app = bot()
    for command in ("/start", "/help", "/cancel", "/unknown"):
        incoming = event(command)
        await app.handle(incoming)
        incoming.reply.assert_awaited_once()
    app.client.send_file.assert_not_awaited()


async def test_command_address():
    app = bot()
    app.username = "MyBot"
    incoming = event("/help@MyBot")
    await app.handle(incoming)
    incoming.reply.assert_awaited_once()
    other = event("/help@AnotherBot")
    await app.handle(other)
    other.reply.assert_not_awaited()


async def test_private_chat_and_allowlist():
    app = bot(allowed_user_ids=frozenset({10}))
    incoming = event("/start")
    await app.handle(incoming)
    assert incoming.reply.call_args.args[0] == "This bot is private."
    incoming.is_private = False
    incoming.reply.reset_mock()
    await app.handle(incoming)
    incoming.reply.assert_not_awaited()


@pytest.mark.parametrize("size", [0, 200_000_001])
async def test_all_media_types_obey_size_limit(size):
    app = bot()
    incoming = event(file=SimpleNamespace(size=size))
    await app.handle(incoming)
    assert "at most" in incoming.reply.call_args.args[0]
    assert app.jobs == {}


async def test_external_url_preserves_query_string_and_releases_slot():
    app = bot()
    url = "https://example.com/image.JPG?signature=abc"
    incoming = event(url)
    await app.handle(incoming)
    app.client.send_file.assert_awaited_once_with("chat", url, reply_to=1, force_document=False)
    assert app.jobs == {}


async def test_link_preview_is_not_uploaded_as_a_file():
    app = bot()
    incoming = event("https://example.com/a", file=SimpleNamespace(size=10))
    incoming.message.media = types.MessageMediaWebPage(types.WebPageEmpty(id=123))
    await app.handle(incoming)
    app.client.send_file.assert_awaited_once()


@pytest.mark.parametrize(
    "link, local",
    [
        ("https://files.example/a", False),
        ("http://127.0.0.1:8080/files/a", True),
        ("http://[::1]:8080/files/a", True),
        ("http://localhost:8080/files/a", True),
        ("http://192.168.1.10/files/a", True),
    ],
)
async def test_upload_reply_explains_private_download_links(link, local, monkeypatch):
    app = bot()
    monkeypatch.setattr("plugins.bot.stream_telegram", AsyncMock(return_value=link))
    incoming = event(file=SimpleNamespace(size=10))
    await app.handle(incoming)
    reply = incoming.reply.return_value.edit.call_args.args[0]
    assert reply.endswith(link)
    assert ("private network" in reply) == local
    assert ("SSH tunnel" in reply) == local
    assert not app.jobs


async def test_busy_and_per_user_limits():
    app = bot(max_transfers=1)
    app.jobs[1] = asyncio.current_task()
    incoming = event("https://example.com/a", user_id=1)
    await app.handle(incoming)
    assert "already" in incoming.reply.call_args.args[0]
    incoming = event("https://example.com/a", user_id=2)
    await app.handle(incoming)
    assert "busy" in incoming.reply.call_args.args[0]
    app.client.send_file.assert_not_awaited()


async def test_cancel_releases_slot():
    app = bot()
    started = asyncio.Event()

    async def block(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()

    app.client.send_file.side_effect = block
    incoming = event("https://example.com/a")
    task = asyncio.create_task(app.handle(incoming))
    await asyncio.wait_for(started.wait(), timeout=2)
    await app.handle(event("/cancel"))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not app.jobs
    assert incoming.reply.return_value.edit.call_args.args[0] == "Transfer cancelled."


@pytest.mark.parametrize(
    "failure",
    [
        TransferError("safe error"),
        ValueError("private URL"),
        errors.FloodWaitError(request=None, capture=3),
        RuntimeError("private URL"),
    ],
)
async def test_error_releases_slot_and_redacts_details(failure):
    app = bot()
    app.client.send_file.side_effect = failure
    incoming = event("https://example.com/a")
    await app.handle(incoming)
    assert not app.jobs
    assert "private URL" not in incoming.reply.return_value.edit.call_args.args[0]


@pytest.mark.parametrize(
    "url",
    [
        "",
        "hello",
        "ftp://example.com/a",
        "https://a:b@example.com",
        "http://localhost/a",
        "http://127.0.0.1/a",
        "http://[::1]/a",
        "http://192.168.1.1/a",
        "http://foo.local/a",
        "https://example.com:bad/a",
        "https://example.com/a\nfoo",
    ],
)
def test_invalid_or_local_links(url):
    assert not public_link(url)
