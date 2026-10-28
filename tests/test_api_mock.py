"""End-to-end API tests in mock mode (no network, no API key)."""

import base64
import os
from io import BytesIO

os.environ["MOCK"] = "1"
os.environ["MODEL_API_KEY"] = ""

from fastapi.testclient import TestClient  # noqa: E402
from PIL import Image  # noqa: E402

from server.agent import scrub  # noqa: E402
from server.main import app  # noqa: E402

client = TestClient(app)


def _frame() -> str:
    buf = BytesIO()
    Image.new("RGB", (768, 576), "gray").save(buf, format="JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def test_health_reports_mock():
    assert client.get("/api/health").json() == {"ok": True, "mock": True}


def test_find_door_loop_with_clarification():
    r = client.post("/api/step", json={"goal": "Çıkış kapısını bul", "frame": _frame()}).json()
    assert r["action"] == "locate" and r["box"] is None and not r["done"]
    sid = r["session_id"]

    r = client.post("/api/step", json={"session_id": sid, "frame": _frame()}).json()
    assert r["action"] == "ask_user" and r["awaiting_reply"]

    r = client.post("/api/step", json={"session_id": sid, "user_reply": "sağdaki", "frame": _frame()}).json()
    assert "saat 1" in r["speak"] and not r["done"]

    r = client.post("/api/step", json={"session_id": sid, "frame": _frame()}).json()
    assert "saat 12" in r["speak"] and r["done"]
    assert any(t["tool"] == "plan" for t in r["trace"])


def test_read_sign_uses_crop_tool():
    r = client.post("/api/step", json={"goal": "Otobüsün numarasını oku", "frame": _frame()}).json()
    sid = r["session_id"]
    r = client.post("/api/step", json={"session_id": sid, "frame": _frame()}).json()
    assert r["action"] == "read_text" and r["done"]
    assert any(t["tool"] == "read_text" for t in r["trace"])


def test_crossing_request_is_refused():
    r = client.post("/api/step", json={"goal": "Karşıya geçebilir miyim?", "frame": _frame()}).json()
    assert r["action"] == "refuse" and r["done"]


def test_medicine_request_is_refused():
    r = client.post("/api/step", json={"goal": "Bu ilacın dozunu oku", "frame": _frame()}).json()
    assert r["action"] == "refuse"


def test_scrub_removes_safety_claims():
    out = scrub("Kapı saat 12 yönünde. Yol güvenli, geçebilirsin.")
    assert "güvenli olduğuna ben karar veremem" in out
    assert "geçebilirsin" not in out


def test_bad_frame_rejected():
    r = client.post("/api/step", json={"goal": "kapı", "frame": "not-base64!!"})
    assert r.status_code == 400


def test_transcribe_mock():
    r = client.post("/api/transcribe", files={"audio": ("s.wav", b"RIFF0000", "audio/wav")})
    assert r.json()["mock"] is True
