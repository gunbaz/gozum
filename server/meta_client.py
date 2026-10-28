"""Thin wrapper around Meta Model API, with a mock mode that makes no calls.

Mock mode is on when MODEL_API_KEY is empty or MOCK=1. In mock mode nothing
leaves the machine, so no credits or card charges are used.
"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Settings:
    api_key: str
    base_url: str
    spark_model: str
    transcribe_model: str
    sam_model: str
    mock: bool

    @classmethod
    def from_env(cls) -> "Settings":
        key = os.getenv("MODEL_API_KEY", "").strip()
        forced = os.getenv("MOCK", "").strip()
        mock = forced == "1" or (forced != "0" and not key)
        return cls(
            api_key=key,
            base_url=os.getenv("META_BASE_URL", "https://api.meta.ai/v1").rstrip("/"),
            spark_model=os.getenv("SPARK_MODEL", "muse-spark-1.3"),
            transcribe_model=os.getenv("TRANSCRIBE_MODEL", "muse-voice-transcribe-1.0"),
            sam_model=os.getenv("SAM_MODEL", "sam-3.1"),
            mock=mock,
        )


def _data_url(jpeg: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()


def parse_json(text: str) -> dict:
    """Pull the first JSON object out of a model reply (tolerates code fences)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object in model reply: {text[:200]!r}")
    return json.loads(match.group(0))


class MetaClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._openai = None
        if not settings.mock:
            from openai import OpenAI

            self._openai = OpenAI(base_url=settings.base_url, api_key=settings.api_key)

    def spark(self, instructions: str, prompt: str, images: list[bytes] | None = None) -> str:
        """One Muse Spark call with optional images; returns the reply text."""
        if self._openai is None:
            raise RuntimeError("spark() called in mock mode")
        content = [{"type": "input_text", "text": prompt}]
        for jpeg in images or []:
            content.append({"type": "input_image", "image_url": _data_url(jpeg)})
        response = self._openai.responses.create(
            model=self.settings.spark_model,
            instructions=instructions,
            input=[{"role": "user", "content": content}],
        )
        return response.output_text

    def transcribe(self, wav: bytes) -> str:
        """Speech-to-text for a short WAV clip.

        TODO(day 2): confirm request fields and response shape against
        /docs/api-reference/voice once credits are live.
        """
        if self.settings.mock:
            raise RuntimeError("transcribe() called in mock mode")
        resp = httpx.post(
            f"{self.settings.base_url}/asr/transcribe",
            headers={"Authorization": f"Bearer {self.settings.api_key}"},
            data={"model": self.settings.transcribe_model, "language": "tr"},
            files={"file": ("speech.wav", wav, "audio/wav")},
            timeout=30,
        )
        resp.raise_for_status()
        body = resp.json()
        return (body.get("text") or "").strip()
