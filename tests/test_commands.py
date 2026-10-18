import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from uploadbot.commands import Commands, file_buttons
from uploadbot.config import Settings
from uploadbot.errors import TransferError
from uploadbot.history import HistoryStore
from uploadbot.models import UploadResult


@pytest_asyncio.fixture
async def commands(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    registry = SimpleNamespace(
        default="default", providers={"default": None, "vault": None}, delete=AsyncMock()
    )
    return Commands(store, registry, Settings(1, "a" * 32, "1:test"), {})


def incoming(user_id=1):
    return SimpleNamespace(
        sender_id=user_id,
        chat_id=user_id,
        is_private=True,
        reply=AsyncMock(),
        respond=AsyncMock(),
        answer=AsyncMock(),
    )


async def record(commands, owner=1):
    return await commands.history.add(
        owner,
        UploadResult(
            "https://files.example/private",
            "report.txt",
            10,
            "default",
            "https://files.example/delete",
        ),
    )


async def test_history_search_and_links_are_owner_scoped(commands):
    stored = await record(commands)
    other = incoming(2)
    await commands.handle(other, "files", "report")
    assert "No matching" in other.reply.call_args.args[0]
    await commands.handle(other, "link", stored.id)
    assert "not found" in other.reply.call_args.args[0]
    own = incoming()
    await commands.handle(own, "files", "REPORT")
    assert stored.id[:8] in own.reply.call_args.args[0]
    await commands.handle(own, "link", stored.id[:8])
    assert stored.result.url in own.reply.call_args.args[0]


async def test_preferences_persist_without_resetting_other_settings(commands):
    event = incoming()
    for name, arg in [("provider", "vault"), ("expiry", "2"), ("encrypt", "on")]:
        await commands.handle(event, name, arg)
    provider, options = await commands.history.preferences(1, "default")
    assert provider == "vault" and options.retention_days == 2 and options.encrypted
    for name, arg in [
        ("provider", "missing"),
        ("expiry", "0"),
        ("expiry", "15"),
        ("encrypt", "yes"),
    ]:
        with pytest.raises(TransferError):
            await commands.handle(event, name, arg)


async def test_simultaneous_preference_updates_preserve_encryption(commands):
    await asyncio.gather(
        commands.handle(incoming(), "encrypt", "on"),
        commands.handle(incoming(), "expiry", "2"),
        commands.handle(incoming(), "provider", "vault"),
    )
    provider, options = await commands.history.preferences(1, "default")
    assert provider == "vault" and options.retention_days == 2 and options.encrypted


async def test_oversized_urls_do_not_create_invalid_url_buttons(commands):
    stored = await commands.history.add(
        1, UploadResult("https://files.example/" + "x" * 2100, "large", 10)
    )
    buttons = file_buttons(stored)
    assert all(not hasattr(button, "url") for row in buttons for button in row)


async def test_remote_delete_must_succeed_before_history_is_removed(commands):
    stored = await record(commands)
    commands.registry.delete.side_effect = TransferError("host unavailable")
    with pytest.raises(TransferError):
        await commands.handle(incoming(), "delete", stored.id)
    assert await commands.history.get(1, stored.id)
    commands.registry.delete.side_effect = None
    await commands.handle(incoming(), "delete", stored.id[:8])
    assert await commands.history.get(1, stored.id) is None


@pytest.mark.parametrize("action", ["copy", "delete"])
async def test_inline_actions_recheck_ownership(commands, action):
    stored = await record(commands)
    event = incoming(2)
    event.data = f"{action}/{stored.id}".encode()
    await commands.callback(event)
    assert "not found" in event.answer.call_args.args[0]
    commands.registry.delete.assert_not_awaited()
    event.respond.assert_not_awaited()
    event = incoming()
    event.data = f"{action}/{stored.id}".encode()
    await commands.callback(event)
    if action == "copy":
        assert event.respond.call_args.args[0] == stored.result.url
    else:
        commands.registry.delete.assert_awaited_once_with(stored.result)


async def test_callbacks_cannot_cancel_someone_else_or_run_in_group(commands):
    task = asyncio.create_task(asyncio.Event().wait())
    commands.jobs[1] = task
    event = incoming(2)
    event.data = b"cancel"
    await commands.callback(event)
    assert not task.cancelling()
    event = incoming()
    event.is_private = False
    event.data = b"cancel"
    await commands.callback(event)
    assert not task.cancelling()
    event.is_private = True
    await commands.callback(event)
    with pytest.raises(asyncio.CancelledError):
        await task
