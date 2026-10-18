"""Private-chat commands and bounded, cancellable transfer jobs."""

import asyncio
import ipaddress
import logging
import time
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from telethon import errors, types

from uploadbot.config import Settings
from uploadbot.transfer import TransferClient, TransferError, stream_telegram, valid_link

logger = logging.getLogger(__name__)


def human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}"
        value /= 1024
    raise AssertionError("unreachable")


def public_link(value: str) -> bool:
    if not valid_link(value):
        return False
    host = urlsplit(value).hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


class UploadBot:
    def __init__(self, client, transfer: TransferClient, settings: Settings):
        self.client = client
        self.transfer = transfer
        self.settings = settings
        self.username = ""
        self.jobs: dict[int, asyncio.Task] = {}

    async def handle(self, event) -> None:
        if not event.is_private:
            return
        user_id = event.sender_id
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            await event.reply("This bot is private.")
            return
        text = (event.raw_text or "").strip()
        if text.startswith("/"):
            token = text.split(maxsplit=1)[0][1:].lower()
            command, _, address = token.partition("@")
            if address and address != self.username.lower():
                return
            if command in {"start", "help"}:
                upload_host = urlsplit(self.settings.transfer_url).hostname
                await event.reply(
                    "UploadBot · files in, links out\n\n"
                    f"Send a file to stream it to {upload_host}.\n"
                    "Send a public HTTP(S) file link to receive it on Telegram.\n\n"
                    f"Files up to {human_size(self.settings.max_file_size)}\n"
                    "/cancel to stop your current transfer\n"
                    "/help to show this message\n\n"
                    "Uploaded files are shared through a link. Retention depends on the server.",
                    parse_mode=None,
                    link_preview=False,
                )
            elif command == "cancel":
                task = self.jobs.get(user_id)
                if task:
                    task.cancel()
                    await event.reply("Stopping your transfer…")
                else:
                    await event.reply("You have no active transfer.")
            else:
                await event.reply("Send a file or a public file link. Use /help for details.")
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
        self.jobs[user_id] = asyncio.current_task()
        status = None
        try:
            status = await event.reply("Streaming file…" if file else "Sending link to Telegram…")
            async with asyncio.timeout(self.settings.transfer_timeout):
                if file:
                    last_update = time.monotonic()

                    async def progress(sent: int, total: int) -> None:
                        nonlocal last_update
                        now = time.monotonic()
                        if now - last_update >= 4:
                            last_update = now
                            await self.edit_status(
                                status, f"Streaming… {sent / total:.0%} · {human_size(sent)}"
                            )

                    link = await stream_telegram(
                        self.client, event.message, self.transfer, progress
                    )
                    notice = ""
                    if not public_link(link):
                        notice = (
                            "This link is on a private network. Open it from the bot server "
                            "or use an SSH tunnel.\n\n"
                        )
                    await self.edit_status(status, f"Upload complete ✓\n\n{notice}{link}")
                else:
                    # Telegram fetches the external URL; the bot never downloads it locally.
                    suffix = PurePosixPath(unquote(urlsplit(text).path)).suffix.lower()
                    media = suffix in {".jpg", ".jpeg", ".png", ".mp4"}
                    await self.client.send_file(
                        await event.get_input_chat(),
                        text,
                        reply_to=event.id,
                        force_document=not media,
                    )
                    await self.edit_status(status, "Sent to Telegram ✓")
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
        finally:
            self.jobs.pop(user_id, None)

    @staticmethod
    async def edit_status(status, text: str) -> None:
        try:
            await status.edit(text, parse_mode=None, link_preview=False)
        except errors.RPCError:
            pass  # Deleted status messages / edit rate limits must not interrupt an upload.

    async def show_error(self, event, status, text: str) -> None:
        if status:
            await self.edit_status(status, text)
        else:
            await event.reply(text, parse_mode=None, link_preview=False)
