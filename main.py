"""Run UploadBot with python main.py."""

import asyncio
import logging

import aiohttp
from telethon import TelegramClient, events

from config import Settings
from plugins.bot import UploadBot
from utils.transfer import TransferClient


async def run(settings: Settings) -> None:
    settings.session_path.parent.mkdir(parents=True, exist_ok=True)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("telethon").setLevel(logging.WARNING)
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        raise SystemExit(f"Invalid configuration. {exc}") from None
    try:
        import uvloop
    except ImportError:
        asyncio.run(run(settings))
    else:
        uvloop.run(run(settings))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
