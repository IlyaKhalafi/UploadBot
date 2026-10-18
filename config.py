"""Validated environment configuration. Importing this module has no side effects."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

DEFAULT_TRANSFER_URL = "https://file2share.us"
FILE2SHARE_MAX_FILE_SIZE = 95_000_000


def positive_int(name: str, default: str) -> int:
    try:
        value = int(os.environ.get(name, default))
    except ValueError:
        raise ValueError(f"{name} must be a positive integer") from None
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


@dataclass(frozen=True)
class Settings:
    api_id: int
    api_hash: str = field(repr=False)
    bot_token: str = field(repr=False)
    transfer_url: str = DEFAULT_TRANSFER_URL
    max_file_size: int = FILE2SHARE_MAX_FILE_SIZE
    max_transfers: int = 3
    transfer_timeout: int = 1800
    allowed_user_ids: frozenset[int] = frozenset()
    session_path: Path = Path("data/uploadbot")

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).with_name(".env"))
        api_id = positive_int("API_ID", "0")
        api_hash = os.environ.get("API_HASH", "").strip()
        bot_token = os.environ.get("BOT_TOKEN", "").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            raise ValueError("API_HASH must be the 32-character hash from my.telegram.org")
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", bot_token):
            raise ValueError("BOT_TOKEN must be a bot token from @BotFather")
        url = os.environ.get("TRANSFER_URL", DEFAULT_TRANSFER_URL).strip().rstrip("/")
        try:
            parts = urlsplit(url)
            valid = (
                parts.scheme in {"http", "https"}
                and parts.hostname
                and parts.port != 0
                and not parts.username
                and not parts.password
                and not parts.query
                and not parts.fragment
                and not any(c.isspace() or ord(c) < 32 for c in url)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "TRANSFER_URL must be an HTTP(S) base URL without credentials or query"
            )
        max_file_size = positive_int("MAX_FILE_SIZE", str(FILE2SHARE_MAX_FILE_SIZE))
        if parts.hostname in {"file2share.us", "www.file2share.us"} and (
            max_file_size > FILE2SHARE_MAX_FILE_SIZE
        ):
            raise ValueError("MAX_FILE_SIZE cannot exceed 95000000 bytes when using File2Share")
        try:
            allowed = frozenset(
                int(item.strip())
                for item in os.environ.get("ALLOWED_USER_IDS", "").split(",")
                if item.strip()
            )
            if any(user_id <= 0 for user_id in allowed):
                raise ValueError
        except ValueError:
            raise ValueError(
                "ALLOWED_USER_IDS must contain comma-separated positive user IDs"
            ) from None
        session_path = os.environ.get("SESSION_PATH", "data/uploadbot").strip()
        if not session_path:
            raise ValueError("SESSION_PATH cannot be empty")
        return cls(
            api_id=api_id,
            api_hash=api_hash,
            bot_token=bot_token,
            transfer_url=url,
            max_file_size=max_file_size,
            max_transfers=positive_int("MAX_CONCURRENT_TRANSFERS", "3"),
            transfer_timeout=positive_int("TRANSFER_TIMEOUT", "1800"),
            allowed_user_ids=allowed,
            session_path=Path(session_path),
        )
