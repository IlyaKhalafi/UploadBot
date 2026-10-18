"""Raw PUT uploads and host metadata parsing."""

import time
from collections.abc import AsyncIterator
from urllib.parse import quote, urlsplit

import aiohttp
from telethon import TelegramClient
from telethon.tl.custom import Message

from uploadbot.errors import HostError, TransferError
from uploadbot.http import Chunk, HostResponse, HTTPTransport, Progress
from uploadbot.models import UploadOptions, UploadResult
from uploadbot.urls import valid_link

CHUNK_SIZE = 512 * 1024


def safe_filename(name: str) -> str:
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(c for c in name if c.isprintable()).strip()
    return name[:180] if name and name not in {".", ".."} else "file.bin"


def same_origin(left: str, right: str) -> bool:
    if not valid_link(left) or not valid_link(right):
        return False
    a, b = urlsplit(left), urlsplit(right)
    return (a.scheme, a.hostname, a.port or (443 if a.scheme == "https" else 80)) == (
        b.scheme,
        b.hostname,
        b.port or (443 if b.scheme == "https" else 80),
    )


def upload_result(
    response: HostResponse,
    base_url: str,
    filename: str,
    size: int,
    name: str,
    options: UploadOptions,
) -> UploadResult:
    link = response.headers.get("x-direct-url")
    if link is None:
        try:
            link = response.body.decode("utf-8").strip()
        except UnicodeDecodeError:
            raise TransferError("Upload server returned an invalid download link.") from None
    else:
        link = link.strip()
    if not valid_link(link) or len(link.encode("utf-8")) > 2048:
        raise TransferError("Upload server returned an invalid download link.")
    deletion = response.headers.get("x-delete-url") or response.headers.get("x-url-delete")
    if deletion and not same_origin(deletion, base_url):
        deletion = None
    native = urlsplit(base_url).hostname in {"file2share.us", "www.file2share.us"}
    return UploadResult(
        link,
        safe_filename(filename),
        size,
        name,
        deletion,
        time.time() + options.retention_days * 86400 if native else None,
        options.encrypted,
    )


class TransferClient:
    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        max_file_size: int,
        *,
        name: str = "file2share",
    ) -> None:
        self.session = session
        self.base_url = base_url.rstrip("/")
        self.max_file_size = max_file_size
        self.name = name
        self.transport = HTTPTransport(session)

    async def upload(
        self,
        chunks: AsyncIterator[Chunk],
        filename: str,
        size: int,
        progress: Progress | None = None,
    ) -> str:
        return (await self.upload_metadata(chunks, filename, size, progress)).url

    async def upload_metadata(
        self,
        chunks: AsyncIterator[Chunk],
        filename: str,
        size: int,
        progress: Progress | None = None,
        *,
        options: UploadOptions | None = None,
    ) -> UploadResult:
        options = options or UploadOptions()
        if options.encrypted:
            raise TransferError("Encrypted uploads require an encrypted byte source.")
        if size <= 0 or size > self.max_file_size:
            raise TransferError("The file is empty or exceeds the configured size limit.")
        response = await self.transport.stream(
            f"{self.base_url}/{quote(safe_filename(filename), safe='')}",
            chunks,
            size,
            progress,
            headers={"Max-Days": str(options.retention_days)},
        )
        return upload_result(response, self.base_url, filename, size, self.name, options)

    async def delete(self, result: UploadResult) -> None:
        if not result.delete_url:
            raise TransferError("This host did not provide a deletion link.")
        if result.provider != self.name or not same_origin(result.delete_url, self.base_url):
            raise TransferError("The deletion link does not belong to this host.")
        try:
            await self.transport.request("DELETE", result.delete_url)
        except HostError as exc:
            if exc.status not in {404, 410}:
                raise


async def stream_telegram(
    client: TelegramClient,
    message: Message,
    transfer: TransferClient,
    progress: Progress | None = None,
) -> str:
    """Close Telegram's borrowed download sender on HTTP errors or cancellation."""
    file = message.file
    if file is None or file.size is None:
        raise TransferError("The Telegram message has no downloadable file with a known size.")
    filename = file.name or f"telegram-{message.id}{file.ext or '.bin'}"
    stream = client.iter_download(message.media, request_size=CHUNK_SIZE, file_size=file.size)
    try:
        return await transfer.upload(stream, filename, file.size, progress)
    finally:
        await stream.close()
