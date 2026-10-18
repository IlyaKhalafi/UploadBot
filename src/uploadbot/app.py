"""Application startup and Telegram client lifecycle."""

import argparse
import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from importlib.metadata import version

import aiohttp
from telethon import TelegramClient, events

from uploadbot.bot import UploadBot
from uploadbot.config import Settings
from uploadbot.transfer import TransferClient


async def run(settings: Settings) -> None:
    settings.session_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    client = TelegramClient(
        str(settings.session_path),
        settings.api_id,
        settings.api_hash,
        flood_sleep_threshold=0,
    )
    timeout = aiohttp.ClientTimeout(
        total=settings.transfer_timeout,
        connect=30,
        sock_read=60,
    )
    async with aiohttp.ClientSession(timeout=timeout) as session:
        transfer = TransferClient(session, settings.transfer_url, settings.max_file_size)
        bot = UploadBot(client, transfer, settings)
        client.add_event_handler(bot.handle, events.NewMessage(incoming=True))
        try:
            await client.start(bot_token=settings.bot_token)
            me = await client.get_me()
            if not me.bot or me.id != int(settings.bot_token.split(":", 1)[0]):
                raise ValueError("Session belongs to another account; use a new SESSION_PATH")
            bot.username = me.username or ""
            logging.getLogger(__name__).info("UploadBot is ready")
            await client.run_until_disconnected()
        finally:
            await client.disconnect()


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="uploadbot", description="Stream Telegram files to the web"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('telegram-uploadbot')}"
    )
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate settings without connecting to Telegram",
    )
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(f"Invalid configuration. {exc}") from None
    if arguments.check_config:
        print("Configuration is valid.")
        return
    with suppress(KeyboardInterrupt):
        try:
            import uvloop
        except ImportError:
            asyncio.run(run(settings))
        else:
            uvloop.run(run(settings))
