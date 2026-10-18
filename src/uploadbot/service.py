"""Coordinate byte sources and providers without storing file contents or keys."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from telethon import TelegramClient
from telethon.tl.custom import Message

from uploadbot.encryption import EncryptedSource
from uploadbot.errors import TransferError
from uploadbot.http import Progress
from uploadbot.models import UploadOptions, UploadResult
from uploadbot.providers import ProviderRegistry
from uploadbot.sources import TelegramSource


@dataclass(frozen=True)
class CompletedUpload:
    result: UploadResult
    key: str | None = field(default=None, repr=False)


class UploadService:
    def __init__(self, client: TelegramClient, registry: ProviderRegistry):
        self.client = client
        self.registry = registry

    async def upload(
        self,
        message: Message,
        provider: str,
        options: UploadOptions,
        progress: Progress | None = None,
        *,
        on_key: Callable[[str], Awaitable[None]] | None = None,
    ) -> CompletedUpload:
        original = TelegramSource(self.client, message)
        source = EncryptedSource(original) if options.encrypted else original
        candidates = (
            list(self.registry.providers.values())
            if provider == "auto"
            else [self.registry.providers.get(provider)]
        )
        if not any(p is not None and source.size <= p.max_file_size for p in candidates):
            raise TransferError(
                "The upload exceeds the selected provider's size limit, "
                "including encryption overhead."
            )
        if isinstance(source, EncryptedSource) and on_key:
            await on_key(source.key_text)
        result = await self.registry.upload(source, provider, options, progress)
        return CompletedUpload(
            result, source.key_text if isinstance(source, EncryptedSource) else None
        )
