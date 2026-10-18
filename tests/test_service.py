from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from test_providers import MemorySource

from uploadbot.encryption import EncryptedSource
from uploadbot.errors import TransferError
from uploadbot.models import UploadOptions, UploadResult
from uploadbot.progress import ProgressMeter
from uploadbot.service import UploadService


@pytest.mark.parametrize("encrypted", [True, False])
async def test_service_encrypts_actual_bytes_and_keeps_key_out_of_result(encrypted, monkeypatch):
    monkeypatch.setattr("uploadbot.service.TelegramSource", lambda *args: MemorySource())
    result = UploadResult("https://example.com/file", "test", 10, encrypted=encrypted)
    registry = SimpleNamespace(
        upload=AsyncMock(return_value=result),
        providers={"default": SimpleNamespace(max_file_size=10_000_000)},
    )
    completed = await UploadService(None, registry).upload(
        None, "default", UploadOptions(encrypted=encrypted)
    )
    source = registry.upload.call_args.args[0]
    assert isinstance(source, EncryptedSource) == encrypted
    assert bool(completed.key) == encrypted
    assert completed.result is result
    assert completed.key is None or completed.key not in repr(completed)


def test_progress_is_throttled_and_never_moves_backwards(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("uploadbot.progress.time.monotonic", lambda: now[0])
    meter = ProgressMeter()
    now[0] = 2
    assert meter.update(10, 100) is None
    now[0] = 4
    text = meter.update(50, 100)
    assert "50%" in text and "12.5 B/s" in text and "ETA 4 s" in text
    now[0] = 8
    assert "50%" in meter.update(20, 100)


async def test_key_delivery_must_succeed_before_encrypted_upload(monkeypatch):
    monkeypatch.setattr("uploadbot.service.TelegramSource", lambda *args: MemorySource())
    registry = SimpleNamespace(
        upload=AsyncMock(), providers={"default": SimpleNamespace(max_file_size=10_000_000)}
    )
    delivery = AsyncMock(side_effect=OSError("chat unavailable"))
    with pytest.raises(OSError):
        await UploadService(None, registry).upload(
            None, "default", UploadOptions(encrypted=True), on_key=delivery
        )
    delivery.assert_awaited_once()
    registry.upload.assert_not_awaited()


async def test_encryption_overhead_is_checked_before_sending_key(monkeypatch):
    monkeypatch.setattr("uploadbot.service.TelegramSource", lambda *args: MemorySource())
    registry = SimpleNamespace(
        upload=AsyncMock(), providers={"default": SimpleNamespace(max_file_size=10)}
    )
    delivery = AsyncMock()
    with pytest.raises(TransferError, match="overhead"):
        await UploadService(None, registry).upload(
            None, "default", UploadOptions(encrypted=True), on_key=delivery
        )
    registry.upload.assert_not_awaited()
    delivery.assert_not_awaited()
