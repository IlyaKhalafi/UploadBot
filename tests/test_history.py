import asyncio
import threading
import time
from dataclasses import replace

import pytest

from uploadbot.history import HistoryStore
from uploadbot.models import UploadOptions, UploadResult


def result(filename="video.mp4"):
    return UploadResult(
        "https://files.example/video", filename, 123, delete_url="https://host/secret"
    )


async def test_history_is_persistent_and_owner_scoped(tmp_path):
    path = tmp_path / "private" / "history.sqlite3"
    store = await HistoryStore.open(path)
    entry = await store.add(1, result())
    assert await store.get(2, entry.id) is None
    assert await store.files(2) == []
    restored = await HistoryStore.open(path)
    assert (await restored.get(1, entry.id[:8])).result == result()
    assert not path.stat().st_mode & 0o077
    assert "secret" not in repr(entry)


async def test_search_is_literal_and_deletion_needs_owner(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    entry = await store.add(1, result("100%_Holiday.MP4"))
    await store.add(1, result("other.txt"))
    assert len(await store.files(1, "holiday")) == 1
    assert len(await store.files(1, "%_")) == 1
    assert await store.files(1, "' OR 1=1 --") == []
    assert not await store.mark_deleted(2, entry.id)
    assert await store.mark_deleted(1, entry.id)
    assert not await store.mark_deleted(1, entry.id)
    assert await store.get(1, entry.id) is None
    assert len(await store.files(1)) == 1


async def test_preferences_do_not_leak_between_users(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    await store.set_preferences(1, "backup", UploadOptions(3, True))
    assert await store.preferences(1, "file2share") == ("backup", UploadOptions(3, True))
    assert await store.preferences(2, "file2share") == ("file2share", UploadOptions())


async def test_concurrent_writes_preserve_every_record(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    await asyncio.gather(*(store.add(1, result(str(i))) for i in range(25)))
    assert len(await store.files(1, limit=50)) == 25


@pytest.mark.parametrize("identifier", ["", "a", "%", "' OR 1=1", "A" * 32])
async def test_bad_identifiers_cannot_select_records(identifier, tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    await store.add(1, result())
    assert await store.get(1, identifier) is None


async def test_expired_records_are_not_live_links(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    entry = await store.add(1, replace(result(), expires_at=time.time() - 1))
    assert await store.get(1, entry.id) is None
    assert await store.files(1) == []
    assert len(await store.files(1, include_expired=True)) == 1


async def test_unicode_search_and_short_id_delete(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    entry = await store.add(1, result("ФОТО.JPG"))
    assert len(await store.files(1, "фото")) == 1
    assert await store.mark_deleted(1, entry.id[:8])
    assert await store.get(1, entry.id[:8]) is None


async def test_repeated_cancellation_waits_for_transaction_and_stays_cancelled(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    started = threading.Event()
    release = threading.Event()

    def failing_operation(db):
        started.set()
        release.wait(5)
        raise RuntimeError("database operation failed")

    task = asyncio.create_task(store._call(failing_operation))
    await asyncio.to_thread(started.wait, 5)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_encryption_key_fragment_is_not_persisted(tmp_path):
    store = await HistoryStore.open(tmp_path / "history.db")
    with pytest.raises(ValueError, match="fragment"):
        await store.add(1, replace(result(), url="https://files.example/a#key", encrypted=True))
    assert await store.files(1) == []
