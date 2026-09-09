FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY packages/ packages/
RUN uv sync --all-packages --no-dev --frozen

ENV PATH="/app/.venv/bin:$PATH"
WORKDIR /run
ENTRYPOINT ["python", "-m", "labtasker_server", "serve"]
