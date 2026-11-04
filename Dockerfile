# Hugging Face Spaces (Docker SDK) expects the app on port 7860 and runs the
# container as a non-root user, so dependencies are installed at build time and
# uvicorn is started straight from the virtualenv.
FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server ./server
COPY public ./public

ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "/app/.venv/bin/uvicorn server.main:app --host 0.0.0.0 --port ${PORT}"]
