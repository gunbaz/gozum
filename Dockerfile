# Hugging Face Spaces (Docker SDK) expects the app on port 7860.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY server ./server
COPY web ./web

ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uv run --no-dev uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
