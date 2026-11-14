FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY services/ services/
RUN uv sync --frozen --no-dev --package vynzo-market-ingestion
ENV PATH="/repo/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "market_ingestion"]
