<p align="center">
  <img src="docs/logo.svg" alt="UploadBot logo" width="128" height="128">
</p>

<h1 align="center">UploadBot</h1>
<p align="center">Files in. Links out.</p>

<p align="center">
  <a href="https://github.com/IlyaKhalafi/UploadBot/actions/workflows/ci.yml"><img src="https://github.com/IlyaKhalafi/UploadBot/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab?logo=python&amp;logoColor=white" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-78dba9" alt="MIT license"></a>
</p>

Send a file to your Telegram bot and get a public download link from
[File2Share](https://file2share.us). Send a public file URL to receive it on Telegram.

UploadBot passes file chunks straight from Telegram into the upload request.
Uploading starts before downloading finishes, with bounded buffers and no
temporary files on the bot host.

```text
Telegram -> 512 KiB chunks -> UploadBot -> File2Share -> Download link
```

## What you get

- **Large files and albums** streamed through File2Share's numbered-part API.
- **Resilient transfers** with failed-part retries, speed, ETA, and cancellation.
- **Your choice of host** with File2Share, compatible PUT hosts, or WebDAV.
- **Private history** with filename search, download buttons, and remote deletion.
- **Optional encryption** with a separate key and a local decryption command.
- **Simple hosting** with uv, Docker Compose, and an optional user allowlist.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Python 3.11+,
a bot token from [BotFather](https://t.me/BotFather), and an API ID/hash from
[my.telegram.org/apps](https://my.telegram.org/apps).

```bash
git clone https://github.com/IlyaKhalafi/UploadBot.git
cd UploadBot
cp .env.example .env
# Fill in API_ID, API_HASH, and BOT_TOKEN in .env.
uv sync --locked --no-dev --extra speed
uv run --no-sync uploadbot
```

No File2Share account or hosting API key is required. For a personal bot, set
`ALLOWED_USER_IDS` in `.env` to your numeric Telegram user ID.

## Try it

| Send in a private chat | Result |
| --- | --- |
| A document, photo, video, or audio file | A public download URL |
| A public HTTP(S) file URL | The file sent back through Telegram |
| `/start` or `/help` | Commands and the configured file limit |
| `/cancel` | Stop your active transfer |
| `/files report` | Find recent uploads by filename |
| `/provider`, `/expiry`, `/encrypt` | Choose settings for future uploads |

Voice messages and animations work too. File URLs must be accessible to Telegram
without browser cookies or a login.

## Hosting limits

The default file limit is **2 GB**, subject to Telegram's own limits. File2Share's
numbered-part API supports files up to **50 GB** when the operator raises the limit.
The host keeps files for **up to 14 days**,
and limits uploads to **40 per hour per IP address**. Anyone with the link can
download the file. Some file types, including programs and web pages, must be
archived first. See the [host's API guide](https://www.file2share.us/cli).

Use `/expiry 2` for shorter retention or `/encrypt on` for encrypted uploads.
Keep the separate key message. See [commands and providers](docs/features.md)
and [decrypting files](docs/encryption.md).

## Run with Docker

Configure `.env`, then start the bot.

```bash
docker compose up --build -d
docker compose logs -f bot
```

The container runs as a non-root user and persists the Telegram session in a named
volume. No incoming port is needed.

## More

- [Setup and configuration](docs/setup.md) for every setting and custom upload hosts.
- [How streaming works](docs/architecture.md) for flow control and failure handling.
- [Contributing](CONTRIBUTING.md) for development commands and tests.
- [Migration notes](CHANGELOG.md#migrating-from-1x) for older installations.

MIT licensed. If UploadBot saves you time, a star helps others find it.
