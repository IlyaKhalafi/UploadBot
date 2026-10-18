"""Bounded HTTP responses and cancellation-safe, backpressured request bodies."""

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import aclosing
from dataclasses import dataclass, field
from typing import TypeAlias

import aiohttp
from telethon import errors

from uploadbot.errors import HostError, TransferError

Chunk: TypeAlias = bytes | memoryview
Progress: TypeAlias = Callable[[int, int], Awaitable[None]]
MAX_RESPONSE_SIZE = 8192


@dataclass(frozen=True)
class HostResponse:
    headers: dict[str, str] = field(repr=False)
    body: bytes = field(repr=False)


class HTTPTransport:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self.session = session

    async def request(self, method: str, url: str, *, data=None, headers=None) -> HostResponse:
        try:
            async with self.session.request(
                method, url, data=data, headers=headers, allow_redirects=False
            ) as response:
                if not 200 <= response.status < 300:
                    try:
                        retry_after = max(0.0, float(response.headers.get("Retry-After", "0")))
                        retry_after = min(retry_after, 60.0) if math.isfinite(retry_after) else 0.0
                    except ValueError:
                        retry_after = 0
                    raise HostError(
                        f"Upload server returned HTTP {response.status}. "
                        "Check the host or try again later.",
                        status=response.status,
                        retry_after=retry_after,
                    )
                body = bytearray()
                async for chunk in response.content.iter_chunked(1024):
                    body.extend(chunk)
                    if len(body) > MAX_RESPONSE_SIZE:
                        raise TransferError("Upload server returned an oversized response.")
                return HostResponse(
                    {key.lower(): value for key, value in response.headers.items()}, bytes(body)
                )
        except TransferError:
            raise
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            cause = exc.__cause__
            while cause:
                if isinstance(cause, (TransferError, errors.RPCError)):
                    raise cause from None
                cause = cause.__cause__
            message = (
                "Transfer timed out. Please try again."
                if isinstance(exc, TimeoutError)
                else ("Could not reach the upload server or the connection was interrupted.")
            )
            raise HostError(message) from None

    async def stream(
        self,
        url: str,
        chunks: AsyncIterator[Chunk],
        size: int,
        progress: Progress | None = None,
        *,
        headers: dict[str, str] | None = None,
    ) -> HostResponse:
        sent = 0
        writer: asyncio.Task | None = None

        async def body() -> AsyncIterator[Chunk]:
            nonlocal sent, writer
            writer = asyncio.current_task()
            async for chunk in chunks:
                if not chunk:
                    continue
                sent += len(chunk)
                if sent > size:
                    raise TransferError("Telegram sent more data than the declared file size.")
                yield chunk
                if progress:
                    await progress(sent, size)
            if sent != size:
                raise TransferError("The Telegram download ended before the file was complete.")

        stream = body()
        try:
            response = await self.request(
                "PUT",
                url,
                data=stream,
                headers={
                    **(headers or {}),
                    "Content-Length": str(size),
                    "Content-Type": "application/octet-stream",
                },
            )
            if sent != size:
                raise TransferError("Upload server responded before the file was complete.")
            return response
        finally:
            parent = asyncio.current_task()
            cancellations = parent.cancelling() if parent else 0
            cancelled = False
            if writer is not None and not writer.done():
                writer.cancel()
                while not writer.done():
                    try:
                        await asyncio.shield(writer)
                    except asyncio.CancelledError:
                        cancelled = cancelled or bool(
                            parent and parent.cancelling() > cancellations
                        )
                        continue
                    except Exception:
                        break
                if not writer.cancelled():
                    writer.exception()
            async with aclosing(stream):
                pass
            if cancelled:
                raise asyncio.CancelledError
