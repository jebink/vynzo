FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /usr/local/bin/uv
WORKDIR /repo
COPY pyproject.toml uv.lock ./
COPY services/ services/
COPY vynzo_batch/ vynzo_batch/
RUN uv sync --frozen --no-dev --package vynzo-api
ENV PATH="/repo/.venv/bin:$PATH"
WORKDIR /repo/services/api
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
