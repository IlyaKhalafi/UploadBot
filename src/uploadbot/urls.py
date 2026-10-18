"""URL validation shared by configuration, uploads, and Telegram commands."""

import ipaddress
from urllib.parse import urlsplit


def valid_link(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return bool(
            parts.scheme in {"http", "https"}
            and parts.hostname
            and parts.port != 0
            and not parts.username
            and not parts.password
            and not any(c.isspace() or ord(c) < 32 for c in value)
        )
    except ValueError:
        return False


def public_link(value: str) -> bool:
    if not valid_link(value):
        return False
    host = (urlsplit(value).hostname or "").lower().rstrip(".")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        return True


def upload_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if valid_link(url):
        parts = urlsplit(url)
        if not parts.query and not parts.fragment:
            return url
    raise ValueError("TRANSFER_URL must be an HTTP(S) base URL without credentials or query")
