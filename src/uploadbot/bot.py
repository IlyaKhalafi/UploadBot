"""Private-chat commands and bounded, cancellable transfer jobs."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from contextlib import suppress
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from telethon import Button, TelegramClient, errors, events, types
from telethon.tl.custom import Message

from uploadbot.commands import Commands, expiry_text, file_buttons
from uploadbot.config import Settings
from uploadbot.errors import TransferError
from uploadbot.history import HistoryStore
from uploadbot.progress import ProgressMeter, human_size
from uploadbot.service import UploadService
from uploadbot.urls import public_link

logger = logging.getLogger(__name__)


class UploadBot:
    def __init__(
        self,
        client: TelegramClient,
        service: UploadService,
        settings: Settings,
        history: HistoryStore,
    ) -> None:
        self.client = client
        self.service = service
        self.history = history
        self.settings = settings
        self.username = ""
        self.jobs: dict[int, asyncio.Task[None]] = {}
        self.commands = Commands(history, service.registry, settings, self.jobs)

    async def handle(self, event: events.NewMessage.Event) -> None:
        if not event.is_private or event.sender_id is None:
            return
        if getattr(event.message, "grouped_id", None):
            return  # Album events own grouped media, avoiding duplicate uploads.
        user_id = event.sender_id
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            await event.reply("This bot is private.")
            return
        text = (event.raw_text or "").strip()
        if text.startswith("/"):
            try:
                await self.handle_command(event, text)
            except TransferError as exc:
                await event.reply(str(exc), parse_mode=None)
            except (sqlite3.Error, errors.RPCError, ValueError) as exc:
                logger.warning("Command failed (%s)", type(exc).__name__)
                with suppress(errors.RPCError):
                    await event.reply("Command failed. Please try again later.")
            return

        # Link previews can expose message.file too; only uploaded media are files.
        file = (
            event.message.file
            if isinstance(
                event.message.media, (types.MessageMediaPhoto, types.MessageMediaDocument)
            )
            else None
        )
        if file:
            if not file.size or file.size > self.settings.max_file_size:
                await event.reply(
                    f"File must be nonempty and at most {human_size(self.settings.max_file_size)}."
                )
                return
        elif not public_link(text):
            await event.reply(
                "Send a file or a valid public HTTP(S) file link. Use /help for details."
            )
            return

        if user_id in self.jobs:
            await event.reply("You already have a transfer running. Use /cancel to stop it.")
            return
        if len(self.jobs) >= self.settings.max_transfers:
            await event.reply("All transfer slots are busy. Please try again shortly.")
            return
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Transfers must run in an asyncio task")
        self.jobs[user_id] = task
        try:
            await self.run_transfer(event, text, is_upload=file is not None)
        finally:
            self.jobs.pop(user_id, None)

    async def handle_album(self, event: events.Album.Event) -> None:
        if not event.is_private or event.sender_id is None:
            return
        user_id = event.sender_id
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            await event.reply("This bot is private.")
            return
        messages = event.messages
        if not messages or any(
            not m.file or not m.file.size or m.file.size > self.settings.max_file_size
            for m in messages
        ):
            await event.reply(
                "Every album file must be nonempty and at most "
                f"{human_size(self.settings.max_file_size)}."
            )
            return
        if user_id in self.jobs or len(self.jobs) >= self.settings.max_transfers:
            await event.reply("Transfer slots are busy. Use /cancel or try again shortly.")
            return
        task = asyncio.current_task()
        if task is None:
            raise RuntimeError("Albums must run in an asyncio task")
        self.jobs[user_id] = task
        try:
            await self.run_transfer(event, "", is_upload=True, messages=messages)
        finally:
            self.jobs.pop(user_id, None)

    async def handle_command(self, event: events.NewMessage.Event, text: str) -> None:
        token = text.split(maxsplit=1)[0][1:].lower()
        command, _, address = token.partition("@")
        if address and address != self.username.lower():
            return
        parts = text.split(maxsplit=1)
        argument = parts[1] if len(parts) > 1 else ""
        if await self.commands.handle(event, command, argument):
            return
        if command in {"start", "help"}:
            upload_host = urlsplit(self.settings.transfer_url).hostname
            await event.reply(
                "UploadBot · files in, links out\n\n"
                f"Send a file to stream it to {upload_host}.\n"
                "Send a public HTTP(S) file link to receive it on Telegram.\n\n"
                f"Files up to {human_size(self.settings.max_file_size)}\n"
                "/files [search] · recent uploads\n"
                "/link ID · retrieve a link\n"
                "/delete ID · delete a hosted file\n"
                "/provider [NAME|auto] · choose a host\n"
                "/expiry [1-14] · retention for new files\n"
                "/encrypt [on|off] · encrypt new uploads\n"
                "/cancel to stop your current transfer\n"
                "/help to show this message\n\n"
                "Uploaded files are shared through a link. Retention depends on the server.",
                parse_mode=None,
                link_preview=False,
            )
        elif command == "cancel":
            task = self.jobs.get(event.sender_id)
            if task:
                task.cancel()
                await event.reply("Stopping your transfer…")
            else:
                await event.reply("You have no active transfer.")
        else:
            await event.reply("Send a file or a public file link. Use /help for details.")

    async def run_transfer(
        self, event, text: str, *, is_upload: bool, messages: list[Message] | None = None
    ) -> None:
        status = None

        def committed() -> None:
            nonlocal status
            status = None

        try:
            status = await event.reply(
                "Streaming file…" if is_upload else "Sending link to Telegram…",
                buttons=Button.inline("Cancel", b"cancel"),
            )
            async with asyncio.timeout(self.settings.transfer_timeout):
                if is_upload:
                    items = messages or [event.message]
                    for index, message in enumerate(items):
                        current = (
                            status
                            if index == 0
                            else await event.reply(
                                f"Streaming file {index + 1} of {len(items)}…",
                                buttons=Button.inline("Cancel", b"cancel"),
                            )
                        )
                        status = current
                        await self.upload_file(message, current, event, on_uploaded=committed)
                        status = None
                else:
                    await self.send_url(event, text, status)
        except asyncio.CancelledError:
            if status:
                await self.edit_status(status, "Transfer cancelled.")
            raise
        except TransferError as exc:
            await self.show_error(event, status, str(exc))
        except TimeoutError:
            await self.show_error(event, status, "Transfer timed out. Please try again.")
        except errors.FloodWaitError as exc:
            await self.show_error(
                event, status, f"Telegram is busy. Try again in {exc.seconds} seconds."
            )
        except (errors.RPCError, ValueError, OSError) as exc:
            logger.warning("Transfer failed (%s)", type(exc).__name__)
            await self.show_error(
                event,
                status,
                "Transfer failed. Check the file/link and try again. "
                "For links, Telegram must be able to fetch the URL directly.",
            )
        except Exception as exc:
            logger.error("Unexpected transfer failure (%s)", type(exc).__name__)
            await self.show_error(event, status, "Transfer failed. Please try again later.")

    async def upload_file(
        self,
        message: Message,
        status: Message,
        event,
        *,
        on_uploaded: Callable[[], None] | None = None,
    ) -> None:
        meter = ProgressMeter()

        async def progress(sent: int, total: int) -> None:
            text = meter.update(sent, total)
            if text:
                await self.edit_status(status, text, buttons=Button.inline("Cancel", b"cancel"))

        provider, options = await self.history.preferences(
            event.sender_id, self.service.registry.default
        )

        async def on_key(key: str) -> None:
            await event.reply(
                f"Decryption key for {message.file.name or 'this file'}\n\n{key}\n\n"
                "Keep this message. Use uploadbot-decrypt after downloading the .ubenc file. "
                "The key is not saved in history. Upload will start now.",
                parse_mode=None,
                link_preview=False,
            )

        completed = await self.service.upload(message, provider, options, progress, on_key=on_key)
        if on_uploaded:
            on_uploaded()
        receipt = asyncio.create_task(self.finish_upload(event, status, completed.result))
        try:
            await asyncio.shield(receipt)
        except asyncio.CancelledError:
            while not receipt.done():
                try:
                    await asyncio.shield(receipt)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not receipt.cancelled():
                receipt.exception()
            raise

    async def finish_upload(self, event, status: Message, result) -> None:
        link = result.url
        try:
            record = await self.history.add(event.sender_id, result)
        except (sqlite3.Error, ValueError):
            record = None
        notice = ""
        if not public_link(link):
            notice = (
                "This link is on a private network. Open it from the bot server "
                "or use an SSH tunnel.\n\n"
            )
        if record:
            text = f"Upload complete ✓ · {record.id[:8]}\n{expiry_text(record)}\n\n{notice}{link}"
        else:
            text = (
                f"Upload complete ✓\nHistory could not be saved. Keep this link.\n\n{notice}{link}"
            )
        try:
            await status.edit(
                text,
                parse_mode=None,
                link_preview=False,
                buttons=file_buttons(record) if record else None,
            )
        except errors.RPCError:
            try:
                await status.edit(text, parse_mode=None, link_preview=False, buttons=None)
            except errors.RPCError:
                await event.reply(text, parse_mode=None, link_preview=False)

    async def send_url(self, event: events.NewMessage.Event, url: str, status: Message) -> None:
        # Telegram fetches the URL; the bot host never downloads it locally.
        suffix = PurePosixPath(unquote(urlsplit(url).path)).suffix.lower()
        media = suffix in {".jpg", ".jpeg", ".png", ".mp4"}
        await self.client.send_file(
            await event.get_input_chat(), url, reply_to=event.id, force_document=not media
        )
        await self.edit_status(status, "Sent to Telegram ✓")

    @staticmethod
    async def edit_status(status: Message, text: str, *, buttons=None) -> None:
        try:
            await status.edit(text, parse_mode=None, link_preview=False, buttons=buttons)
        except errors.RPCError:
            pass  # Deleted status messages / edit rate limits must not interrupt an upload.

    async def show_error(
        self, event: events.NewMessage.Event, status: Message | None, text: str
    ) -> None:
        if status:
            await self.edit_status(status, text)
        else:
            await event.reply(text, parse_mode=None, link_preview=False)
