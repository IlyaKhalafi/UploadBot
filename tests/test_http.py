import asyncio
import math

import pytest
from aiohttp import web

from uploadbot.errors import HostError
from uploadbot.http import HostResponse, HTTPTransport


@pytest.mark.parametrize("value", ["inf", "nan", "1000000000", "bad", "-5", "12"])
async def test_retry_after_is_finite_and_bounded(value, server_factory, session):
    async def handler(request):
        return web.Response(status=429, headers={"Retry-After": value})

    transport = HTTPTransport(session)
    with pytest.raises(HostError) as failure:
        await transport.request("POST", await server_factory(handler))
    assert math.isfinite(failure.value.retry_after)
    assert 0 <= failure.value.retry_after <= 60


async def test_cancel_during_writer_cleanup_is_preserved(session, monkeypatch):
    started = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    transport = HTTPTransport(session)

    async def source():
        yield b"a"
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cleaning.set()
            await release.wait()
            raise

    async def request(method, url, *, data, headers):
        async def consume():
            async for _ in data:
                pass

        asyncio.create_task(consume())
        await started.wait()
        return HostResponse({}, b"")

    monkeypatch.setattr(transport, "request", request)
    task = asyncio.create_task(transport.stream("https://example.com", source(), 2))
    await asyncio.wait_for(cleaning.wait(), 2)
    task.cancel()
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
