"""HTTP entry point: serves the web app and the agent API.

Camera frames and audio are processed in memory only; nothing is written to
disk or logged.
"""

from __future__ import annotations

import base64
import binascii
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from .agent import Agent, Session  # noqa: E402  (needs env loaded first)
from .meta_client import MetaClient, Settings  # noqa: E402

# On Vercel, public/ is served by the CDN; locally and in Docker, by FastAPI.
WEB_DIR = Path(__file__).resolve().parent.parent / "public"
MAX_FRAME_BYTES = 3 * 1024 * 1024
MAX_AUDIO_BYTES = 4 * 1024 * 1024

settings = Settings.from_env()
client = MetaClient(settings)
agent = Agent(client)

app = FastAPI(title="Gözüm")


class StepRequest(BaseModel):
    state: dict | None = None  # agent state returned by the previous step
    goal: str | None = None
    user_reply: str | None = None
    frame: str  # JPEG as a data URL or bare base64


def _decode_frame(frame: str) -> bytes:
    payload = frame.split(",", 1)[1] if frame.startswith("data:") else frame
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(400, "frame is not valid base64")
    if len(data) > MAX_FRAME_BYTES:
        raise HTTPException(413, "frame too large")
    return data


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "mock": settings.mock}


@app.post("/api/transcribe")
async def transcribe(audio: UploadFile = File(...)) -> dict:
    wav = await audio.read()
    if len(wav) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "audio too large")
    if settings.mock:
        return {"text": "Çıkış kapısını bul", "mock": True}
    try:
        return {"text": client.transcribe(wav), "mock": False}
    except Exception as exc:  # surface API errors to the client, without the audio
        raise HTTPException(502, f"transcription failed: {type(exc).__name__}")


@app.post("/api/step")
def step(req: StepRequest) -> dict:
    session = Session(goal=req.goal.strip()) if req.goal else Session.from_dict(req.state)
    if req.user_reply:
        session.user_reply = req.user_reply.strip()
    if not session.goal:
        raise HTTPException(400, "no goal set for this session")

    frame = _decode_frame(req.frame)
    try:
        result = agent.step(session, frame)
    except Exception as exc:
        raise HTTPException(502, f"agent step failed: {type(exc).__name__}")
    return {
        "state": session.to_dict(),
        "speak": result.speak,
        "done": result.done,
        "action": result.action,
        "box": result.box,
        "awaiting_reply": result.awaiting_reply,
        "trace": result.trace,
        "mock": settings.mock,
    }


if WEB_DIR.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
