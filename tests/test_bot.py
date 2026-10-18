import asyncio
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telethon import errors, types

from uploadbot.bot import UploadBot
from uploadbot.config import Settings
from uploadbot.models import StoredUpload, UploadOptions, UploadResult
from uploadbot.service import CompletedUpload
from uploadbot.transfer import TransferError
from uploadbot.urls import public_link


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
    registry = SimpleNamespace(default="default", providers={"default": None})
    service = SimpleNamespace(registry=registry, upload=AsyncMock())
    history = SimpleNamespace(
        preferences=AsyncMock(return_value=("default", UploadOptions())), add=AsyncMock()
    )
    return UploadBot(SimpleNamespace(send_file=AsyncMock()), service, config, history)


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


@pytest.mark.parametrize("size", [0, 2_000_000_001])
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
async def test_upload_reply_explains_private_download_links(link, local):
    app = bot()
    result = UploadResult(link, "file.bin", 10, "default")
    app.service.upload.return_value = CompletedUpload(result)
    app.history.add.return_value = StoredUpload("a" * 32, 1, result, 0)
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


async def test_album_uploads_each_file_once_and_releases_slot():
    app = bot()
    items = [event(file=SimpleNamespace(size=10)).message for _ in range(3)]
    for item in items:
        item.grouped_id = 123
    incoming = event(file=SimpleNamespace(size=10))
    incoming.message.grouped_id = 123
    await app.handle(incoming)
    incoming.reply.assert_not_awaited()
    incoming.messages = items
    app.upload_file = AsyncMock()
    await app.handle_album(incoming)
    assert [c.args[0] for c in app.upload_file.call_args_list] == items
    assert not app.jobs


async def test_album_cancellation_stops_remaining_files():
    app = bot()
    started = asyncio.Event()
    completed = []

    async def upload(message, *args, **kwargs):
        if completed:
            started.set()
            await asyncio.Event().wait()
        completed.append(message)

    app.upload_file = upload
    incoming = event()
    incoming.messages = [event(file=SimpleNamespace(size=10)).message for _ in range(3)]
    task = asyncio.create_task(app.handle_album(incoming))
    await asyncio.wait_for(started.wait(), 2)
    await app.handle(event("/cancel"))
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(completed) == 1
    assert not app.jobs


async def test_history_failure_does_not_hide_a_completed_download_link():
    app = bot()
    result = UploadResult("https://files.example/saved", "file.bin", 10, "default")
    app.service.upload.return_value = CompletedUpload(result)
    app.history.add.side_effect = sqlite3.OperationalError("disk unavailable")
    incoming = event(file=SimpleNamespace(size=10))
    await app.handle(incoming)
    text = incoming.reply.return_value.edit.call_args.args[0]
    assert "Upload complete" in text and result.url in text
    assert "History could not be saved" in text


async def test_cancelling_after_host_success_preserves_receipt():
    app = bot()
    result = UploadResult("https://files.example/complete", "file.bin", 10, "default")
    app.service.upload.return_value = CompletedUpload(result)
    started, release = asyncio.Event(), asyncio.Event()

    async def save(*args):
        started.set()
        await release.wait()
        return StoredUpload("a" * 32, 1, result, 0)

    app.history.add.side_effect = save
    incoming = event(file=SimpleNamespace(size=10))
    task = asyncio.create_task(app.handle(incoming))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    text = incoming.reply.return_value.edit.call_args.args[0]
    assert "Upload complete" in text and result.url in text
    assert not app.jobs


async def test_final_receipt_falls_back_to_new_reply_when_edits_fail():
    app = bot()
    result = UploadResult("https://files.example/complete", "file.bin", 10, "default")
    app.history.add.return_value = StoredUpload("a" * 32, 1, result, 0)
    incoming = event()
    status = SimpleNamespace(edit=AsyncMock(side_effect=errors.MessageIdInvalidError(None)))
    await app.finish_upload(incoming, status, result)
    assert status.edit.await_count == 2
    assert result.url in incoming.reply.call_args.args[0]


async def test_failed_next_album_status_cannot_overwrite_completed_link():
    app = bot()
    incoming = event()
    incoming.messages = [event(file=SimpleNamespace(size=10)).message for _ in range(2)]
    first = SimpleNamespace(edit=AsyncMock())
    incoming.reply.side_effect = [first, errors.MessageIdInvalidError(None), SimpleNamespace()]

    async def upload(message, status, event, *, on_uploaded):
        await status.edit("completed link")
        on_uploaded()

    app.upload_file = upload
    await app.handle_album(incoming)
    first.edit.assert_awaited_once_with("completed link")
    assert not app.jobs


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
