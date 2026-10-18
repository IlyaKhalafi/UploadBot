# Contributing to UploadBot

Useful contributions include transfer-server compatibility fixes, reproducible bug
reports, and improvements to streaming reliability or setup instructions.

## Run locally

Use Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --locked --extra speed
uv run --no-sync ruff check .
uv run --no-sync ruff format --check .
uv run --no-sync pytest -q
uv run --no-sync pip-audit --skip-editable
```

Tests use a local HTTP server and fake Telegram messages. No bot token, Telegram
API credentials, or File2Share access is required. The streaming tests
verify upload begins before the source finishes, compare a 64 MiB transfer's
SHA-256 digest, and check bounded Python memory allocations.

## Dependency updates

`pyproject.toml` defines runtime dependencies, optional speed packages, and the
development group. `uv.lock` locks the full dependency graph. Local installs,
Docker builds, and CI all use that lock. After changing dependencies, update the
lock and run the checks above. The audit checks the installed locked environment.

```bash
uv lock --upgrade
uv sync --locked --extra speed
```

## Pull requests

Runtime code lives in `src/uploadbot`. Run the installed `uploadbot` command or
`python -m uploadbot` through uv. Build distributions with `uv build`.
The command handler, configuration, HTTP transport, and shared URL validation
live in separate modules. Keep their public interfaces typed and avoid coupling
the streaming transport to chat formatting.

Describe the problem and resulting behavior. Include reproduction steps or tests
for streaming, cancellation, or protocol changes. Keep network buffers bounded,
close Telegram download iterators, and avoid writing file contents to local disk.
Do not log tokens, session credentials, or private file URLs. Screenshots or chat
transcripts should use sample data.

For performance claims, record the Python/dependency versions, transfer size,
upload/download bandwidth, concurrency, and measurement method. Local synthetic
results do not establish Telegram or public-host throughput.
