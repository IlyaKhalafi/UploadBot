import asyncio
import hashlib
import tracemalloc
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from aiohttp import web

from utils.transfer import CHUNK_SIZE, TransferClient, TransferError, safe_filename, stream_telegram


async def chunks(*blocks):
    for block in blocks:
        yield block


async def test_upload_starts_before_telegram_finishes(server_factory, session):
    received_first = asyncio.Event()
    payload = b"first chunk" + b"last chunk"
    progress = AsyncMock()

    async def handler(request):
        assert request.method == "PUT"
        assert request.content_length == len(payload)
        assert request.content_type == "application/octet-stream"
        assert request.path == "/prefix/a file#?.txt"
        first = await request.content.readexactly(len(b"first chunk"))
        received_first.set()
        assert first + await request.read() == payload
        return web.Response(text="https://files.example/id/a%20file.txt\n")

    async def source():
        yield b"first chunk"
        # A whole-file buffering implementation deadlocks here.
        await asyncio.wait_for(received_first.wait(), timeout=2)
        yield b"last chunk"

    url = await server_factory(handler)
    transfer = TransferClient(session, url + "/prefix", 1000)
    link = await transfer.upload(source(), "../../a file#?.txt", len(payload), progress)
    assert link == "https://files.example/id/a%20file.txt"
    progress.assert_awaited()


@pytest.mark.parametrize("status", [301, 307, 308, 403, 413, 429, 500, 503])
async def test_http_errors_and_redirects_are_not_replayed(status, server_factory, session):
    calls = 0

    async def handler(request):
        nonlocal calls
        calls += 1
        await request.read()
        return web.Response(status=status, headers={"Location": "/other"})

    transfer = TransferClient(session, await server_factory(handler), 100)
    with pytest.raises(TransferError, match=f"HTTP {status}"):
        await transfer.upload(chunks(b"hello"), "a.txt", 5)
    assert calls == 1


@pytest.mark.parametrize(
    "response", [b"<html>oops</html>", b"file:///etc/passwd", b"\xff", b"x" * 9000]
)
async def test_bad_server_responses(response, server_factory, session):
    async def handler(request):
        await request.read()
        return web.Response(body=response)

    transfer = TransferClient(session, await server_factory(handler), 100)
    with pytest.raises(TransferError, match="invalid download link|oversized response"):
        await transfer.upload(chunks(b"hello"), "a.txt", 5)


@pytest.mark.parametrize("size", [0, -1, 101])
async def test_size_rejected_before_network_or_source_read(size, session):
    source = Mock()
    transfer = TransferClient(session, "http://127.0.0.1:1", 100)
    with pytest.raises(TransferError, match="size limit"):
        await transfer.upload(source, "a", size)
    source.assert_not_called()


@pytest.mark.parametrize("block", [b"short", b"too much data for the declared size"])
async def test_actual_size_mismatch(block, server_factory, session):
    async def handler(request):
        await request.read()
        return web.Response(text="https://files.example/a")

    transfer = TransferClient(session, await server_factory(handler), 100)
    with pytest.raises(TransferError):
        await transfer.upload(chunks(block), "a", 10)


async def test_download_failure_is_not_success(server_factory, session):
    async def handler(request):
        await request.read()
        return web.Response(text="https://files.example/a")

    async def source():
        yield b"first"
        raise OSError("interrupted")

    transfer = TransferClient(session, await server_factory(handler), 100)
    with pytest.raises(TransferError):
        await transfer.upload(source(), "a", 10)


async def test_timeout(server_factory):
    async def handler(request):
        await request.read()
        await asyncio.Event().wait()

    url = await server_factory(handler)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=0.05)) as session:
        transfer = TransferClient(session, url, 100)
        with pytest.raises(TransferError, match="timed out"):
            await transfer.upload(chunks(b"hello"), "a", 5)


@pytest.mark.parametrize("status", [200, 413, 500])
async def test_early_response_stops_the_source(status, server_factory, session):
    source_closed = asyncio.Event()

    async def handler(request):
        await request.content.readexactly(1)
        return web.Response(status=status, text="https://files.example/a")

    async def source():
        try:
            yield b"a"
            await asyncio.Event().wait()
        finally:
            source_closed.set()

    transfer = TransferClient(session, await server_factory(handler), 100)
    generator = source()
    try:
        with pytest.raises(TransferError):
            await transfer.upload(generator, "a", 10)
        await asyncio.wait_for(source_closed.wait(), timeout=2)
    finally:
        await generator.aclose()


async def test_cancel_during_real_http_upload(server_factory, session):
    received_first = asyncio.Event()
    source_closed = asyncio.Event()

    async def handler(request):
        await request.content.readexactly(1)
        received_first.set()
        await request.read()
        return web.Response(text="https://files.example/a")

    async def source():
        try:
            yield b"a"
            await asyncio.Event().wait()
        finally:
            source_closed.set()

    transfer = TransferClient(session, await server_factory(handler), 100)
    generator = source()
    task = asyncio.create_task(transfer.upload(generator, "a", 10))
    try:
        await asyncio.wait_for(received_first.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(source_closed.wait(), timeout=2)
    finally:
        await generator.aclose()


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
async def test_telegram_stream_always_closed(outcome):
    stream = SimpleNamespace(close=AsyncMock())
    client = SimpleNamespace(iter_download=Mock(return_value=stream))
    transfer = SimpleNamespace(upload=AsyncMock(return_value="https://files.example/a"))
    if outcome == "failure":
        transfer.upload.side_effect = TransferError("Failed")
    elif outcome == "cancel":
        transfer.upload.side_effect = asyncio.CancelledError()
    message = SimpleNamespace(
        file=SimpleNamespace(size=10, name=None, ext=".jpg"),
        id=42,
        media=object(),
    )
    if outcome == "success":
        assert await stream_telegram(client, message, transfer) == "https://files.example/a"
    else:
        with pytest.raises(TransferError if outcome == "failure" else asyncio.CancelledError):
            await stream_telegram(client, message, transfer)
    stream.close.assert_awaited_once()
    client.iter_download.assert_called_once_with(
        message.media,
        request_size=CHUNK_SIZE,
        file_size=10,
    )
    assert transfer.upload.call_args.args[1] == "telegram-42.jpg"


async def test_large_stream_preserves_checksum_with_bounded_memory(server_factory, session):
    block = b"z" * CHUNK_SIZE
    count = 128  # 64 MiB, generated one chunk at a time.
    expected = hashlib.sha256()
    for _ in range(count):
        expected.update(block)

    async def source():
        for _ in range(count):
            yield block

    async def handler(request):
        digest = hashlib.sha256()
        async for part in request.content.iter_chunked(CHUNK_SIZE):
            digest.update(part)
        assert digest.digest() == expected.digest()
        return web.Response(text="https://files.example/large")

    transfer = TransferClient(session, await server_factory(handler), count * CHUNK_SIZE)
    tracemalloc.start()
    try:
        await transfer.upload(source(), "large.bin", count * CHUNK_SIZE)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    # Includes both HTTP client and local server allocations, but excludes native buffers.
    assert peak < 16 * 1024 * 1024


@pytest.mark.parametrize(
    "name, expected",
    [
        ("../../hello.txt", "hello.txt"),
        ("C:\\tmp\\hello.txt", "hello.txt"),
        ("\r\n", "file.bin"),
        ("..", "file.bin"),
        ("a" * 300, "a" * 180),
    ],
)
def test_safe_filename(name, expected):
    assert safe_filename(name) == expected
