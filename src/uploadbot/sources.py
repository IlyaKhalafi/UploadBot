"""Replayable byte sources. Retries reopen Telegram at a byte offset."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, aclosing, asynccontextmanager
from typing import Protocol

from telethon import TelegramClient
from telethon.tl.custom import Message

from uploadbot.errors import TransferError
from uploadbot.http import Chunk
from uploadbot.transfer import CHUNK_SIZE, safe_filename


class ReplaySource(Protocol):
    filename: str
    size: int
    encrypted: bool

    def open(
        self, offset: int = 0, length: int | None = None
    ) -> AbstractAsyncContextManager[AsyncIterator[Chunk]]: ...


class TelegramSource:
    encrypted = False

    def __init__(self, client: TelegramClient, message: Message) -> None:
        file = message.file
        if file is None or file.size is None or file.size <= 0:
            raise TransferError("The Telegram message has no nonempty downloadable file.")
        self.client = client
        self.message = message
        self.size = file.size
        self.filename = safe_filename(file.name or f"telegram-{message.id}{file.ext or '.bin'}")

    @asynccontextmanager
    async def open(
        self, offset: int = 0, length: int | None = None
    ) -> AsyncIterator[AsyncIterator[Chunk]]:
        count = self.size - offset if length is None else length
        if offset < 0 or count < 0 or offset + count > self.size:
            raise ValueError("Requested range is outside the file")
        aligned = offset - offset % CHUNK_SIZE
        stream = self.client.iter_download(
            self.message.media, request_size=CHUNK_SIZE, file_size=self.size, offset=aligned
        )

        async def limited() -> AsyncIterator[Chunk]:
            remaining = count
            skip = offset - aligned
            if not remaining:
                return
            async for chunk in stream:
                if not chunk:
                    continue
                if skip:
                    skipped = min(skip, len(chunk))
                    skip -= skipped
                    chunk = chunk[skipped:]
                    if not chunk:
                        continue
                part = chunk[:remaining]
                remaining -= len(part)
                yield part
                if not remaining:
                    return
            if remaining:
                raise TransferError(
                    "Telegram ended the download before the requested range was complete."
                )

        try:
            async with aclosing(limited()) as chunks:
                yield chunks
        finally:
            await stream.close()
