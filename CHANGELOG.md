# Changelog

## 2.0.0

- Use File2Share by default, return its direct download URLs, and enforce its
  95 MB single-request upload limit.
- Stream Telegram file chunks into a raw HTTP PUT request, removing temporary
  downloads and blocking HTTP requests.
- Replace Pyrogram with Telethon; pin current runtime and optional speed packages.
- Reuse one asynchronous HTTP session across transfers.
- Add bounded concurrency, one job per user, progress updates, `/help`, and `/cancel`.
- Apply the size limit to every supported Telegram file, not just documents.
- Validate server responses and handle upload errors, timeouts, and interrupted streams.
- Fetch public file links through Telegram, preserving signed query strings.
- Load validated environment settings and support an optional user allowlist.
- Replace interactive startup and Replit self-pinging with standard process hosting.
- Add Docker Compose, a full dependency lock, CI, regression tests, and contributor docs.
- Package runtime code under `src/uploadbot` and use uv for installs, builds,
  development tools, Docker, and CI.

### Migrating from 1.x

Requires Python 3.11+. Copy credentials from your old `config.py` into `.env` using
`.env.example`; `API_ID` is the correct variable name. Old Pyrogram session files
are not compatible with Telethon. The default new session lives at
`data/uploadbot.session`. `REPL_URL` and the Replit self-ping helper were removed.

Set `TRANSFER_URL=https://file2share.us` and `MAX_FILE_SIZE=95000000` in `.env`.
File2Share retains uploads for up to 14 days. Custom PUT upload hosts remain
supported through `TRANSFER_URL`, with retention controlled by that host.

Run `uv sync --locked --no-dev --extra speed` and `uv run --no-sync uploadbot`.
The root `main.py` entry point and requirements files have been removed.
`pyproject.toml` and `uv.lock` define the installation.
