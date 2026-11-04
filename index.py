"""Vercel entrypoint: Vercel's Python runtime looks for `app` in index.py."""

from server.main import app  # noqa: F401
