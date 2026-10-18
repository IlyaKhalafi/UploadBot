<p align="center">
  <img src="docs/logo.svg" alt="UploadBot logo" width="144" height="144">
</p>

<h1 align="center">UploadBot</h1>
<p align="center">Files in. Links out.</p>

<p align="center">
  <a href="https://github.com/IlyaKhalafi/UploadBot/actions/workflows/ci.yml"><img src="https://github.com/IlyaKhalafi/UploadBot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&amp;logoColor=white" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-78dba9" alt="MIT license"></a>
</p>

**Turn Telegram files into shareable links as they stream.** Send a document,
photo, video, or audio file to the bot and receive a public download URL from
[File2Share](https://file2share.us). Send a public file URL to receive it on Telegram.

```text
Telegram -> 512 KiB chunks -> UploadBot -> HTTP PUT -> File2Share
                                  │
                         No temporary file
```

## Why UploadBot?

- **Start uploading immediately.** Telegram chunks feed directly into an
  asynchronous HTTP upload, without waiting for the full download.
- **Keep memory bounded.** Backpressure and a configurable concurrency limit
  keep file size from becoming buffer size.
- **Stay responsive.** Shared HTTP connections, optional native cryptography and
  uvloop, progress updates, and cancellable transfers.
- **Run it your way.** Environment configuration, an optional user allowlist,
  Docker Compose, and support for custom upload hosts.

## File2Share hosting

The default host is `https://file2share.us`. No hosting account or API key is
needed. UploadBot streams each file in a single PUT request and returns the
direct file URL supplied by File2Share.

- Files can be up to **95 MB** (`95000000` bytes).
- File2Share keeps uploads for **up to 14 days**.
- The host allows **40 uploads per hour per IP address**.
- Anyone with the download link can access the file.
- Programs and web pages such as `.exe`, `.apk`, `.html`, and `.svg` are rejected
  by the host. Archive those files before sending them.

These are the host's limits, documented in the
[File2Share command-line guide](https://www.file2share.us/cli). Larger files need
File2Share's separate chunked upload API, which UploadBot does not implement.
Increasing `MAX_FILE_SIZE` above 95 MB is rejected when File2Share is selected.

Custom hosts can be configured with `TRANSFER_URL`. They must accept raw PUT
uploads at `/<filename>` and return a download URL in the response body or the
`X-Direct-Url` header. Limits and retention depend on the selected host.

## Quick start

Requires **Python 3.11+**, a Telegram bot token from
[@BotFather](https://t.me/BotFather), and an API ID/hash from
[my.telegram.org/apps](https://my.telegram.org/apps). The API ID/hash are also
required for bot accounts because UploadBot uses Telegram's MTProto interface.

```bash
git clone https://github.com/IlyaKhalafi/UploadBot.git
cd UploadBot
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
python -m pip install --no-deps .
cp .env.example .env
# Fill in API_ID, API_HASH, and BOT_TOKEN in .env.
python main.py
```

On Windows, activate with `.venv\Scripts\activate`. The lock includes optional
speed packages; uvloop is automatically skipped on Windows. For a minimal
installation without speed extras, use `python -m pip install -r requirements.txt`.

Using [uv](https://docs.astral.sh/uv/)? Install the same locked environment with
`uv sync --locked --extra speed`, then run `uv run --no-sync python main.py`.
Startup is noninteractive and works with a service manager.

## Use it

| Send to the bot | Result |
| --- | --- |
| `/start` or `/help` | Welcome message, file limit, and commands |
| A document, photo, video, audio, voice message, or animation | Stream to File2Share and return a public download URL |
| A public HTTP(S) file URL | Ask Telegram to fetch and send the file |
| `/cancel` | Stop your active transfer |

The bot operates in private chats. Each user can run one transfer at a time;
additional requests receive a busy message. Uploaded files are accessible through
their sharing URL. File2Share removes uploads after up to 14 days.

For URL → Telegram, the URL must point to a file Telegram can fetch without login
or browser cookies. Telegram imposes its own type and size limits. Signed query
strings are preserved. The bot host does not download these URLs.

## Configuration

Copy [.env.example](.env.example) to `.env`. Existing environment variables take
precedence. Keep `.env` and Telegram session files private; both are gitignored.

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_ID` | Required | Telegram application API ID |
| `API_HASH` | Required | Telegram application API hash |
| `BOT_TOKEN` | Required | Your bot's BotFather token |
| `TRANSFER_URL` | `https://file2share.us` | Upload host base URL; HTTPS recommended |
| `MAX_FILE_SIZE` | `95000000` | Maximum Telegram to host file size, in bytes (95 MB) |
| `MAX_CONCURRENT_TRANSFERS` | `3` | Total active transfers; one per user |
| `TRANSFER_TIMEOUT` | `1800` | Per-transfer time limit in seconds |
| `ALLOWED_USER_IDS` | Empty | Comma-separated Telegram user IDs; empty permits everyone |
| `SESSION_PATH` | `data/uploadbot` | Persistent Telethon session path |

Use `ALLOWED_USER_IDS` for a personal bot. Increasing concurrency trades more
network connections and bounded per-transfer buffers for more simultaneous work.
`MAX_FILE_SIZE` applies to files received from Telegram. Telegram controls limits
when it fetches a URL directly. For custom hosts, set `MAX_FILE_SIZE` to a limit
that the host supports.

Existing installations should update both settings in `.env`.

```dotenv
TRANSFER_URL=https://file2share.us
MAX_FILE_SIZE=95000000
```

## Docker

Configure `.env` first, then run the following command.

```bash
docker compose up --build -d
docker compose logs -f bot
```

The container runs as a non-root user. A named volume persists the Telegram
session, and no incoming port is required. Stop with `docker compose down`.

## Performance and reliability

The old flow downloaded a file to disk and then uploaded it using a blocking
HTTP call. The new flow removes temporary file I/O and starts the upload while
the Telegram download is still in progress. Memory remains bounded by chunks and
transport buffers rather than file size. Actual throughput depends on Telegram,
your network, and the upload host; no universal speed multiplier is claimed.

Uploads use raw PUT requests with a known `Content-Length`. File2Share returns
the direct download URL in its `X-Direct-Url` response header. HTTP failures,
incomplete downloads, invalid response URLs, and timeouts are reported as errors.
Redirects are rejected. Configure the final upload endpoint. Interrupted uploads
are not resumed or automatically retried; resend the file when ready.

See [the architecture guide](docs/architecture.md) for flow control, cleanup, and
known limitations, including [local test downloads](docs/architecture.md#local-test-downloads).
Upgrading an older installation? Read the
[migration notes](CHANGELOG.md#migrating-from-1x).

## Development

```bash
uv sync --locked --extra dev --extra speed
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -q
```

Tests run offline against a local HTTP server and simulated Telegram messages.
They cover streaming before the download completes, byte integrity, bounded
Python allocations, HTTP errors, size limits, cancellation, and configuration.
CI runs on Python 3.11 through 3.14.

Read [CONTRIBUTING.md](CONTRIBUTING.md) to report a bug or contribute a fix.
If UploadBot is useful to you, a GitHub star helps other people discover it.

## License

[MIT](LICENSE).
