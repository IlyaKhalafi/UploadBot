"""Replayable uploads to File2Share, generic PUT hosts, and WebDAV."""

import asyncio
import ipaddress
import json
import math
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import TypeVar
from urllib.parse import quote, urlsplit

import aiohttp

from uploadbot.errors import HostError, TransferError
from uploadbot.http import HTTPTransport, Progress
from uploadbot.models import UploadOptions, UploadResult
from uploadbot.sources import ReplaySource
from uploadbot.transfer import same_origin, upload_result
from uploadbot.urls import upload_base_url

T = TypeVar("T")
FILE2SHARE_LIMIT = 50_000_000_000
RETRY_DELAY = 1.0


class CompletionUncertain(TransferError):
    """A non-idempotent completion may already have published a file."""


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    kind: str
    url: str
    public_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,32}", self.name) or self.name == "auto":
            raise ValueError(
                "Provider names must contain 1 to 32 letters, digits, dashes or underscores"
            )
        if self.kind not in {"file2share", "put", "webdav"}:
            raise ValueError("Provider kind must be file2share, put or webdav")
        object.__setattr__(self, "url", upload_base_url(self.url))
        if self.public_url:
            object.__setattr__(self, "public_url", upload_base_url(self.public_url))
        if any(
            not isinstance(k, str) or not isinstance(v, str) or "\n" in k + v or "\r" in k + v
            for k, v in self.headers.items()
        ):
            raise ValueError("Provider headers must be single-line strings")
        forbidden = {
            "host",
            "content-length",
            "transfer-encoding",
            "connection",
            "content-type",
            "max-days",
        }
        if any(key.lower() in forbidden for key in self.headers):
            raise ValueError("Provider headers cannot override HTTP framing or routing")
        parts = urlsplit(self.url)
        if self.headers and parts.scheme != "https":
            try:
                loopback = ipaddress.ip_address(parts.hostname or "").is_loopback
            except ValueError:
                loopback = parts.hostname == "localhost"
            if not loopback:
                raise ValueError("Provider credentials require HTTPS")


async def retry(operation: Callable[[], Awaitable[T]], attempts: int = 3) -> T:
    for attempt in range(attempts):
        try:
            return await operation()
        except HostError as exc:
            if not exc.retryable or attempt + 1 == attempts or exc.retry_after > 60:
                raise
            await asyncio.sleep(max(exc.retry_after, min(2**attempt, 8) * RETRY_DELAY))
    raise AssertionError("unreachable")


class Provider:
    def __init__(self, session: aiohttp.ClientSession, config: ProviderConfig, max_file_size: int):
        self.config = config
        self.name = config.name
        self.base_url = config.url.rstrip("/")
        self.max_file_size = (
            min(max_file_size, FILE2SHARE_LIMIT) if config.kind == "file2share" else max_file_size
        )
        self.transport = HTTPTransport(session)
        self.single_limit = 95_000_000

    async def upload(
        self, source: ReplaySource, options: UploadOptions, progress: Progress | None = None
    ) -> UploadResult:
        if options.encrypted != source.encrypted:
            raise TransferError("Encryption settings do not match the byte source.")
        if not 0 < source.size <= self.max_file_size:
            raise TransferError("The file exceeds this provider's size limit.")
        if self.config.kind == "file2share" and source.size > self.single_limit:
            return await self._multipart(source, options, progress)
        object_name = (
            f"{uuid.uuid4().hex}-{source.filename}"
            if self.config.kind in {"webdav", "put"}
            else source.filename
        )
        endpoint = f"{self.base_url}/{quote(object_name, safe='')}"

        async def send() -> UploadResult:
            async with source.open() as chunks:
                response = await self.transport.stream(
                    endpoint,
                    chunks,
                    source.size,
                    progress,
                    headers={**self.config.headers, "Max-Days": str(options.retention_days)},
                )
            if self.config.kind == "webdav":
                public = (self.config.public_url or self.base_url).rstrip("/")
                return UploadResult(
                    f"{public}/{quote(object_name, safe='')}",
                    source.filename,
                    source.size,
                    self.name,
                    endpoint,
                    encrypted=source.encrypted,
                )
            return self._result(
                response, self.base_url, source.filename, source.size, self.name, options
            )

        # WebDAV reuses one object URL across retries. Plain PUT hosts may leave an orphan.
        return await retry(send)

    async def _multipart(
        self, source: ReplaySource, options: UploadOptions, progress: Progress | None
    ) -> UploadResult:
        async def start():
            return await self.transport.request(
                "POST",
                f"{self.base_url}/api/v1/uploads",
                data={"name": source.filename, "size": str(source.size)},
                headers=self.config.headers,
            )

        response = await retry(start)
        try:
            info = json.loads(response.body)
            if not isinstance(info, dict):
                raise ValueError
            identifier = info["upload_id"]
            part_size, parts = info["part_size"], info["parts"]
            if type(part_size) is not int or type(parts) is not int:
                raise ValueError
            if not isinstance(identifier, str) or not re.fullmatch(
                r"[A-Za-z0-9_-]{1,128}", identifier
            ):
                raise ValueError
            if not 1 <= part_size <= 50 * 1024 * 1024 or parts != math.ceil(
                source.size / part_size
            ):
                raise ValueError
            if parts > 10000:
                raise ValueError
        except (ValueError, TypeError, KeyError, ZeroDivisionError, RecursionError):
            raise TransferError("File2Share returned invalid upload parameters.") from None
        shown = 0

        for number in range(1, parts + 1):
            offset = (number - 1) * part_size
            size = min(part_size, source.size - offset)

            async def part_progress(sent: int, total: int, *, offset: int = offset) -> None:
                nonlocal shown
                shown = max(shown, offset + sent)
                if progress:
                    await progress(shown, source.size)

            async def send_part(
                *,
                offset: int = offset,
                size: int = size,
                number: int = number,
                report: Progress = part_progress,
            ) -> None:
                async with source.open(offset, size) as chunks:
                    await self.transport.stream(
                        f"{self.base_url}/api/v1/uploads/{identifier}/{number}",
                        chunks,
                        size,
                        report,
                        headers=self.config.headers,
                    )

            await retry(send_part)

        async def complete():
            return await self.transport.request(
                "POST",
                f"{self.base_url}/api/v1/uploads/{identifier}/complete",
                headers={**self.config.headers, "Max-Days": str(options.retention_days)},
            )

        # File2Share returns 404 after an already successful completion. Repeating
        # this POST cannot recover a lost success response, unlike numbered parts.
        try:
            response = await complete()
        except HostError as exc:
            if exc.retryable:
                raise CompletionUncertain(
                    "The host did not confirm completion. The file may have been published; "
                    "automatic fallback was stopped."
                ) from None
            raise
        return self._result(
            response, self.base_url, source.filename, source.size, self.name, options
        )

    def _result(self, response, base, filename, size, name, options) -> UploadResult:
        result = upload_result(response, base, filename, size, name, options)
        if self.config.kind == "file2share":
            result = replace(result, expires_at=time.time() + options.retention_days * 86400)
        return result

    async def delete(self, result: UploadResult) -> None:
        if not result.delete_url or result.provider != self.name:
            raise TransferError("This provider did not supply a deletion link.")
        if not same_origin(result.delete_url, self.base_url):
            raise TransferError("The deletion link does not belong to this provider.")
        try:
            await self.transport.request("DELETE", result.delete_url, headers=self.config.headers)
        except HostError as exc:
            if exc.status not in {404, 410}:
                raise


class ProviderRegistry:
    def __init__(self, providers: list[Provider]):
        if not providers or len({provider.name for provider in providers}) != len(providers):
            raise ValueError("Providers must have unique names")
        self.providers = {provider.name: provider for provider in providers}
        self.default = providers[0].name

    async def upload(
        self,
        source: ReplaySource,
        choice: str,
        options: UploadOptions,
        progress: Progress | None = None,
    ) -> UploadResult:
        if choice != "auto" and choice not in self.providers:
            raise TransferError("That upload provider is no longer configured. Use /provider.")
        candidates = list(self.providers.values()) if choice == "auto" else [self.providers[choice]]
        failure: TransferError | None = None
        for provider in candidates:
            try:
                return await provider.upload(source, options, progress)
            except CompletionUncertain:
                raise
            except TransferError as exc:
                failure = exc
        raise failure or TransferError("No upload provider is available.")

    async def delete(self, result: UploadResult) -> None:
        provider = self.providers.get(result.provider)
        if provider is None:
            raise TransferError("The upload provider is no longer configured.")
        await provider.delete(result)
