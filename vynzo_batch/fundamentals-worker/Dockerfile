FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY services/ services/
COPY vynzo_batch/ vynzo_batch/
RUN uv sync --frozen --no-dev --package vynzo-fundamentals-worker
ENV PATH="/repo/.venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "fundamentals_worker"]
