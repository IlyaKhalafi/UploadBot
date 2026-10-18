from contextlib import asynccontextmanager
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from uploadbot.errors import HostError, TransferError
from uploadbot.models import UploadOptions
from uploadbot.providers import (
    CompletionUncertain,
    Provider,
    ProviderConfig,
    ProviderRegistry,
    retry,
)


class MemorySource:
    filename = "test.bin"
    encrypted = False

    def __init__(self, data=b"0123456789"):
        self.data = data
        self.size = len(data)
        self.ranges = []

    @asynccontextmanager
    async def open(self, offset=0, length=None):
        self.ranges.append((offset, length))

        async def chunks():
            yield self.data[offset:] if length is None else self.data[offset : offset + length]

        yield chunks()


async def test_numbered_parts_resume_without_replaying_confirmed_parts(
    server_factory, session, monkeypatch
):
    monkeypatch.setattr("uploadbot.providers.RETRY_DELAY", 0)
    calls = {}
    received = {}
    retention = []

    async def handler(request):
        path = request.path
        calls[path] = calls.get(path, 0) + 1
        if path == "/api/v1/uploads":
            form = await request.post()
            assert form["size"] == "10"
            return web.json_response(dict(upload_id="abc", part_size=4, parts=3))
        if path.endswith("complete"):
            retention.append(request.headers["Max-Days"])
            return web.Response(
                text="https://download.example/file", headers={"X-Delete-Url": base + "/delete/abc"}
            )
        body = await request.read()
        if path.endswith("/2") and calls[path] == 1:
            return web.Response(status=503)
        received[int(path.rsplit("/", 1)[-1])] = body
        return web.Response(text="ok")

    base = await server_factory(handler)
    provider = Provider(session, ProviderConfig("f2s", "file2share", base), 100)
    provider.single_limit = 4
    source = MemorySource()
    progress = AsyncMock()
    result = await provider.upload(source, UploadOptions(2), progress)
    assert source.ranges == [(0, 4), (4, 4), (4, 4), (8, 2)]
    assert b"".join(received[i] for i in range(1, 4)) == source.data
    assert retention == ["2"]
    assert result.delete_url == base + "/delete/abc"
    assert result.expires_at is not None
    values = [call.args[0] for call in progress.call_args_list]
    assert values == sorted(values) and values[-1] == 10


async def test_webdav_retries_same_object_and_deletes_with_profile_credentials(
    server_factory, session, monkeypatch
):
    monkeypatch.setattr("uploadbot.providers.RETRY_DELAY", 0)
    puts = []
    deletes = []

    async def handler(request):
        assert request.headers["Authorization"] == "Bearer private"
        if request.method == "DELETE":
            deletes.append(request.path)
            return web.Response(status=204)
        puts.append((request.path, await request.read()))
        return web.Response(status=503 if len(puts) == 1 else 201)

    base = await server_factory(handler)
    config = ProviderConfig(
        "dav",
        "webdav",
        base + "/",
        "https://public.example/files",
        {"Authorization": "Bearer private"},
    )
    provider = Provider(session, config, 100)
    result = await provider.upload(MemorySource(), UploadOptions())
    assert puts[0] == puts[1]
    assert result.url.startswith("https://public.example/files/")
    assert result.expires_at is None
    await provider.delete(result)
    assert deletes == [puts[0][0]]
    with pytest.raises(TransferError):
        await provider.delete(replace(result, delete_url="https://other.example/delete"))


@pytest.mark.parametrize(
    "params",
    [
        dict(upload_id="../bad", part_size=4, parts=3),
        dict(upload_id="ok", part_size=0, parts=3),
        dict(upload_id="ok", part_size=1000000000, parts=1),
        dict(upload_id="ok", part_size=4, parts=2),
    ],
)
async def test_invalid_part_parameters_do_not_read_source(params, server_factory, session):
    async def handler(request):
        return web.json_response(params)

    base = await server_factory(handler)
    provider = Provider(session, ProviderConfig("f", "file2share", base), 100)
    provider.single_limit = 1
    source = MemorySource()
    with pytest.raises(TransferError, match="parameters"):
        await provider.upload(source, UploadOptions())
    assert not source.ranges


async def test_fallback_requires_explicit_auto_and_encryption_must_match(session):
    first = Provider(session, ProviderConfig("first", "put", "https://first.example"), 100)
    second = Provider(session, ProviderConfig("second", "put", "https://second.example"), 100)
    registry = ProviderRegistry([first, second])
    with pytest.raises(TransferError, match="Encryption"):
        await first.upload(MemorySource(), UploadOptions(encrypted=True))
    first.upload = AsyncMock(side_effect=TransferError("failed"))
    second.upload = AsyncMock(return_value="success")
    with pytest.raises(TransferError):
        await registry.upload(MemorySource(), "first", UploadOptions())
    second.upload.assert_not_awaited()
    assert await registry.upload(MemorySource(), "auto", UploadOptions()) == "success"


async def test_permanent_http_errors_are_not_retried():
    operation = AsyncMock(side_effect=HostError("denied", status=403))
    with pytest.raises(HostError):
        await retry(operation)
    operation.assert_awaited_once()


async def test_uncertain_completion_is_not_retried_or_sent_to_another_provider(
    server_factory, session
):
    completions = 0

    async def handler(request):
        nonlocal completions
        if request.path == "/api/v1/uploads":
            return web.json_response(dict(upload_id="abc", part_size=10, parts=1))
        if request.path.endswith("complete"):
            completions += 1
            return web.Response(status=503)
        await request.read()
        return web.Response(text="ok")

    base = await server_factory(handler)
    first = Provider(session, ProviderConfig("first", "file2share", base), 100)
    first.single_limit = 1
    second = Provider(session, ProviderConfig("second", "put", base), 100)
    second.upload = AsyncMock()
    with pytest.raises(CompletionUncertain):
        await ProviderRegistry([first, second]).upload(MemorySource(), "auto", UploadOptions())
    assert completions == 1
    second.upload.assert_not_awaited()


def test_profile_credentials_require_https_outside_loopback():
    with pytest.raises(ValueError, match="HTTPS"):
        ProviderConfig("test", "webdav", "http://example.com", headers={"Authorization": "secret"})


@pytest.mark.parametrize(
    "headers", [{"Content-Length": "9"}, {"Max-Days": "99"}, {"X-Key": "bad\nheader"}]
)
def test_profile_headers_are_validated(headers):
    with pytest.raises(ValueError):
        ProviderConfig("test", "put", "https://example.com", headers=headers)
