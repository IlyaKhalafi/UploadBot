# Changelog

## 2.1.0

- Support File2Share's numbered-part API for large files, with a 2 GB default limit.
- Retry temporary failures and resume failed parts from Telegram byte ranges.
- Add selectable PUT and WebDAV profiles with explicitly enabled fallback.
- Keep private upload history with filename search, expiry estimates, and deletion.
- Upload albums sequentially and preserve completed links when cancelled.
- Add optional streaming AES-256-GCM-SIV encryption and `uploadbot-decrypt`.
- Show speed and ETA with inline download, share, copy-link, delete, and cancel actions.
- Keep encryption keys outside hosted files, URLs, and history metadata.
- Apply concurrent preference changes atomically so encryption settings are preserved.

Existing `.env` files keep their configured file limit. Set
`MAX_FILE_SIZE=2000000000` to enable the new default on an existing installation.
Increase `TRANSFER_TIMEOUT` for slow connections or large albums. History metadata
is stored beside the Telegram session and needs the same backup protection.

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
