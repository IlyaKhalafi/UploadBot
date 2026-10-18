# Setup and configuration

Use [uv](https://docs.astral.sh/uv/getting-started/installation/) to install the
environment locked in `uv.lock`. `pyproject.toml` defines the package and its
dependencies. Running `uv sync --locked --no-dev --extra speed` installs the bot
with optional native cryptography and uvloop. Skip `--extra speed` for the minimal
installation. uvloop is automatically omitted on Windows.

Run `uv run --no-sync uploadbot` or `uv run --no-sync python -m uploadbot`.
Neither command needs virtual environment activation. Run from the project
directory to load its `.env`, or provide configuration through environment
variables when running an installed package elsewhere.

Use `uv run --no-sync uploadbot --check-config` to validate settings without a
network connection. `uv run --no-sync uploadbot --version` prints the installed
version without reading credentials.

## Credentials

Create a bot with [BotFather](https://t.me/BotFather). Get the application API ID
and hash from [my.telegram.org/apps](https://my.telegram.org/apps). All three
credentials are needed because UploadBot uses Telegram's MTProto interface.

Copy `.env.example` to `.env` and fill in the credentials. Environment variables
take precedence over `.env`. Keep the environment file and Telegram session
private. Both are excluded from Git and Docker build contexts.

## Settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_ID` | Required | Telegram application API ID |
| `API_HASH` | Required | Telegram application API hash |
| `BOT_TOKEN` | Required | Your bot's BotFather token |
| `TRANSFER_URL` | `https://file2share.us` | Upload host base URL |
| `MAX_FILE_SIZE` | `95000000` | Maximum Telegram to host file size, in bytes |
| `MAX_CONCURRENT_TRANSFERS` | `3` | Total active transfers, with one per user |
| `TRANSFER_TIMEOUT` | `1800` | Time limit for one transfer, in seconds |
| `ALLOWED_USER_IDS` | Empty | Comma-separated Telegram user IDs; empty permits everyone |
| `SESSION_PATH` | `data/uploadbot` | Persistent Telethon session path |

For a personal bot, restrict `ALLOWED_USER_IDS` to your own Telegram user ID.
Increasing concurrency allows more simultaneous work and uses more connections
and per-transfer buffers. New requests receive a busy reply when all slots are
occupied. There is no unbounded waiting queue.

`MAX_FILE_SIZE` applies to incoming Telegram files. When a user sends a URL,
Telegram fetches it directly and imposes its own limits.

## Upload hosts

File2Share accepts a raw PUT upload at `/<filename>` and returns the direct file
URL in the `X-Direct-Url` response header. Its response body contains a sharing
page URL. UploadBot prefers the direct URL so it works in download clients.

The default file limit is 95,000,000 bytes. Raising it above that value is rejected
when File2Share is selected. Files are retained for up to 14 days, and the host
allows 40 uploads per hour per IP address. Programs and web pages such as `.exe`,
`.apk`, `.html`, and `.svg` must be archived first. These are host restrictions,
documented in the [File2Share API guide](https://www.file2share.us/cli).

Custom hosts must accept raw PUT uploads at `/<filename>` and return a URL in the
`X-Direct-Url` header or a plain URL in the response body. Set `TRANSFER_URL` and
`MAX_FILE_SIZE` to match the host. HTTPS is recommended. Retention and access
rules depend on the selected host.

Configure the final endpoint because upload redirects are rejected. Files are
not automatically retried or resumed after a failure. A local test receiver can
return loopback URLs that only work on the bot's machine. See
[local test downloads](architecture.md#local-test-downloads).

## Docker Compose

Compose reads `.env`, runs as a non-root user, and stores the Telegram session in
a named volume. Uploaded file bytes are not stored in that volume. No incoming
port is needed for Telegram or File2Share.

```bash
docker compose up --build -d
docker compose logs -f bot
docker compose down
```

If you change `SESSION_PATH`, keep it under `/app/data` in the container so it
remains writable and persists in the volume.
