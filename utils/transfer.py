"""Backpressured HTTP uploads; never buffer an entire file or write it to disk."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress
from urllib.parse import quote, urlsplit

import aiohttp

CHUNK_SIZE = 512 * 1024
MAX_RESPONSE_SIZE = 8192
Progress = Callable[[int, int], Awaitable[None]]


class TransferError(Exception):
    """A transfer failed with a message safe to show to the user."""


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable()).strip()
    return name[:180] if name and name not in {".", ".."} else "file.bin"


def valid_link(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return bool(
            parts.scheme in {"http", "https"}
            and parts.hostname
            and parts.port != 0
            and not parts.username
            and not parts.password
            and not any(c.isspace() or ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


class TransferClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str, max_file_size: int):
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.max_file_size = max_file_size

    async def upload(
        self,
        chunks: AsyncIterator[bytes],
        filename: str,
        size: int,
        progress: Progress | None = None,
    ) -> str:
        """PUT raw chunks with a known length. The caller owns the source iterator."""
        if size <= 0 or size > self.max_file_size:
            raise TransferError("The file is empty or exceeds the configured size limit.")
        sent = 0
        writer: asyncio.Task | None = None

        async def body() -> AsyncIterator[bytes]:
            nonlocal sent, writer
            writer = asyncio.current_task()
            async for chunk in chunks:
                if not chunk:
                    continue
                sent += len(chunk)
                if sent > size or sent > self.max_file_size:
                    raise TransferError("Telegram sent more data than the declared file size.")
                yield chunk
                if progress:
                    await progress(sent, size)
            if sent != size:
                raise TransferError("The Telegram download ended before the file was complete.")

        @asynccontextmanager
        async def managed_body():
            stream = body()
            try:
                yield stream
            finally:
                # aiohttp writes the body in a separate task. On cancellation before
                # response headers arrive, wait for that task before closing the stream.
                if writer is not None and not writer.done():
                    writer.cancel()
                    with suppress(asyncio.CancelledError, Exception):
                        await writer
                await stream.aclose()

        url = f"{self.base_url}/{quote(safe_filename(filename), safe='')}"
        try:
            async with managed_body() as stream:
                async with self.session.put(
                    url,
                    data=stream,
                    headers={
                        "Content-Length": str(size),
                        "Content-Type": "application/octet-stream",
                    },
                    allow_redirects=False,
                ) as response:
                    if not 200 <= response.status < 300:
                        raise TransferError(
                            f"Upload server returned HTTP {response.status}. "
                            "Check TRANSFER_URL or try again later."
                        )
                    result = bytearray()
                    async for chunk in response.content.iter_chunked(1024):
                        result.extend(chunk)
                        if len(result) > MAX_RESPONSE_SIZE:
                            raise TransferError("Upload server returned an oversized response.")
                    if sent != size:
                        raise TransferError("Upload server responded before the file was complete.")
                    # File2Share returns a page in the body and the actual file URL
                    # in this header. Other compatible hosts can return just a URL.
                    link = response.headers.get("X-Direct-Url")
                    if link is None:
                        try:
                            link = result.decode("utf-8").strip()
                        except UnicodeDecodeError:
                            raise TransferError(
                                "Upload server returned an invalid download link."
                            ) from None
                    else:
                        link = link.strip()
                    if not valid_link(link):
                        raise TransferError("Upload server returned an invalid download link.")
                    return link
        except TransferError:
            raise
        except (aiohttp.ClientError, OSError, TimeoutError) as exc:
            cause = exc.__cause__
            while cause:
                if isinstance(cause, TransferError):
                    raise cause from None
                cause = cause.__cause__
            if isinstance(exc, TimeoutError):
                raise TransferError("Transfer timed out. Please try again.") from None
            raise TransferError(
                "Could not reach the upload server or the connection was interrupted."
            ) from None


async def stream_telegram(client, message, transfer: TransferClient, progress=None) -> str:
    """Close Telegram's borrowed download sender on HTTP errors or cancellation."""
    file = message.file
    filename = file.name or f"telegram-{message.id}{file.ext or '.bin'}"
    stream = client.iter_download(message.media, request_size=CHUNK_SIZE, file_size=file.size)
    try:
        return await transfer.upload(stream, filename, file.size, progress)
    finally:
        await stream.close()
