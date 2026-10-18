"""Owner-scoped history, preferences, and inline file actions."""

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlencode

from telethon import Button

from uploadbot.config import Settings
from uploadbot.errors import TransferError
from uploadbot.history import HistoryStore
from uploadbot.models import StoredUpload
from uploadbot.progress import human_size
from uploadbot.providers import ProviderRegistry
from uploadbot.urls import public_link


def file_buttons(record: StoredUpload):
    buttons = []
    if public_link(record.result.url):
        row = []
        share = "https://t.me/share/url?" + urlencode({"url": record.result.url})
        if len(record.result.url.encode()) <= 2048:
            row.append(Button.url("Download", record.result.url))
        if len(share.encode()) <= 2048:
            row.append(Button.url("Share", share))
        if row:
            buttons.append(row)
    buttons.append([Button.inline("Copy link", f"copy/{record.id}")])
    if record.result.delete_url:
        buttons[-1].append(Button.inline("Delete", f"delete/{record.id}"))
    return buttons


def expiry_text(record: StoredUpload) -> str:
    expiry = record.result.expires_at
    if expiry is None:
        return "Expiry is controlled by the host"
    return "Expires around " + datetime.fromtimestamp(expiry, UTC).strftime("%Y-%m-%d %H.%M UTC")


class Commands:
    def __init__(
        self,
        history: HistoryStore,
        registry: ProviderRegistry,
        settings: Settings,
        jobs: dict[int, asyncio.Task],
    ):
        self.history, self.registry, self.settings, self.jobs = history, registry, settings, jobs

    async def handle(self, event, command: str, argument: str) -> bool:
        user_id = event.sender_id
        if command == "files":
            records = await self.history.files(user_id, argument)
            lines = [
                f"{r.id[:8]} · {r.result.filename} · {human_size(r.result.size)}\n{expiry_text(r)}"
                for r in records
            ]
            await event.reply(
                "\n\n".join(lines) + "\n\n/link ID to retrieve a link · /delete ID to remove a file"
                if lines
                else "No matching uploads in your recent history.",
                parse_mode=None,
                link_preview=False,
            )
        elif command in {"link", "delete"}:
            record = await self.history.get(user_id, argument.strip())
            if record is None:
                await event.reply("File not found in your active history. Use /files.")
            elif command == "delete":
                await self.delete(user_id, record)
                await event.reply("File deleted from the host and your active history.")
            else:
                await event.reply(
                    f"{record.result.filename}\n{expiry_text(record)}\n\n{record.result.url}",
                    buttons=file_buttons(record),
                    parse_mode=None,
                    link_preview=False,
                )
        elif command in {"provider", "expiry", "encrypt"}:
            provider, options = await self.history.preferences(user_id, self.registry.default)
            value = argument.strip()
            if command == "provider":
                if value:
                    if value not in {*self.registry.providers, "auto"}:
                        raise TransferError(
                            "Unknown provider. Use /provider to see available names."
                        )
                    provider = value
                names = ", ".join(self.registry.providers)
                reply = (
                    f"Selected provider {provider}\nAvailable {names}\n"
                    "/provider NAME to select one\n"
                    "/provider auto allows fallback to other configured hosts."
                )
            elif command == "expiry":
                if value:
                    if not value.isascii() or not value.isdecimal() or not 1 <= int(value) <= 14:
                        raise TransferError("Use /expiry with a number from 1 to 14.")
                    options = replace(options, retention_days=int(value))
                reply = (
                    f"Requested retention {options.retention_days} days for future uploads. "
                    "File2Share supports this setting. Other hosts control their own expiry."
                )
            else:
                if value:
                    if value not in {"on", "off"}:
                        raise TransferError("Use /encrypt on or /encrypt off.")
                    options = replace(options, encrypted=value == "on")
                state = "on" if options.encrypted else "off"
                reply = (
                    f"Encryption is {state} for future uploads. "
                    "Encrypted files need uploadbot-decrypt and the separate key message. "
                    "Keep that key; it is not stored in history."
                )
            if value:
                changes = {
                    "provider": {"provider": provider},
                    "expiry": {"retention_days": options.retention_days},
                    "encrypt": {"encrypted": options.encrypted},
                }[command]
                await self.history.update_preferences(user_id, self.registry.default, **changes)
            await event.reply(reply, parse_mode=None, link_preview=False)
        else:
            return False
        return True

    async def delete(self, user_id: int, record: StoredUpload) -> None:
        if record.user_id != user_id:
            raise TransferError("This upload does not belong to you.")
        await self.registry.delete(record.result)
        try:
            removed = await self.history.mark_deleted(user_id, record.id)
            if not removed and await self.history.get(user_id, record.id) is not None:
                raise sqlite3.OperationalError
        except sqlite3.Error:
            raise TransferError(
                "Deleted on the host, but history cleanup failed. Retry /delete with the same ID."
            ) from None

    async def callback(self, event) -> None:
        user_id = event.sender_id
        if not event.is_private or user_id is None or event.chat_id != user_id:
            await event.answer("Use these buttons in your private chat.", alert=True)
            return
        if self.settings.allowed_user_ids and user_id not in self.settings.allowed_user_ids:
            await event.answer("This bot is private.", alert=True)
            return
        data = event.data.decode("ascii", errors="replace")
        if data == "cancel":
            task = self.jobs.get(user_id)
            if task:
                task.cancel()
            await event.answer("Stopping your transfer…" if task else "No active transfer.")
            return
        action, _, identifier = data.partition("/")
        if action not in {"copy", "delete"}:
            await event.answer("Unknown action.")
            return
        record = await self.history.get(user_id, identifier)
        if record is None:
            await event.answer("File not found in your active history.", alert=True)
            return
        await event.answer()
        try:
            if action == "copy":
                # MTProto has no clipboard button. A plain message supports long-press Copy.
                await event.respond(record.result.url, parse_mode=None, link_preview=False)
            else:
                await self.delete(user_id, record)
                await event.respond("File deleted from the host and your active history.")
        except TransferError as exc:
            await event.respond(str(exc), parse_mode=None, link_preview=False)
