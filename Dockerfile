FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra speed --no-install-project
COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra speed --no-editable --compile-bytecode

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
RUN useradd --create-home --uid 10001 bot \
    && mkdir /app/data \
    && chown bot:bot /app/data

USER bot
CMD ["uploadbot"]
