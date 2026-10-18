# Contributing to UploadBot

Useful contributions include transfer-server compatibility fixes, reproducible bug
reports, and improvements to streaming reliability or setup instructions.

## Run locally

Use Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked --extra dev --extra speed
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -q
uv run --no-sync pip-audit -r requirements.lock --require-hashes --disable-pip
```

Tests use a local HTTP server and fake Telegram messages. No bot token, Telegram
API credentials, or public transfer.sh instance is required. The streaming tests
verify upload begins before the source finishes, compare a 64 MiB transfer's
SHA-256 digest, and check bounded Python memory allocations.

## Dependency updates

`pyproject.toml` defines direct dependencies; `uv.lock` locks their full dependency
graph. `requirements.lock` is the runtime export used by Docker. After changing
versions, regenerate both locks and run the checks above.

```bash
uv lock --upgrade
uv export --locked --extra speed --no-dev --no-extra dev --no-emit-project --output-file requirements.lock
```

## Pull requests

Describe the problem and resulting behavior. Include reproduction steps or tests
for streaming, cancellation, or protocol changes. Keep network buffers bounded,
close Telegram download iterators, and avoid writing file contents to local disk.
Do not log tokens, session credentials, or private file URLs. Screenshots or chat
transcripts should use sample data.

For performance claims, record the Python/dependency versions, transfer size,
upload/download bandwidth, concurrency, and measurement method. Local synthetic
results do not establish Telegram or public-host throughput.
