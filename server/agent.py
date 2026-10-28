"""Find-and-guide agent loop.

Each call to `Agent.step` handles one camera frame: Muse Spark plans the next
action as JSON, then the server executes it (direction math, crop-and-read,
clarifying question) and returns what to say plus a visible trace.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field

from . import geometry
from .meta_client import MetaClient, parse_json

MAX_STEPS = 12

PLANNER_INSTRUCTIONS = """\
Sen Gözüm'sün: görme engelli kullanıcılar için Türkçe yön ve nesne bulma ajanı.
Kullanıcının bir hedefi var. Her turda bir kamera karesi alırsın ve SADECE şu JSON'u döndürürsün:
{"action": "locate" | "read_text" | "ask_user" | "whats_ahead" | "done",
 "target": "<hedefin kısa Türkçe adı>",
 "box": [x0, y0, x1, y1] veya null,
 "speak": "<kullanıcıya söylenecek en fazla iki kısa Türkçe cümle>"}

Kurallar:
- box, karede hedefin (veya okunacak yazının) konumudur: 0-1000 normalize ızgara, sol üst (0,0).
- Hedef görünmüyorsa action "locate", box null, speak ise yavaş bir hareket talimatı olsun ("Telefonu yavaşça sağa çevir").
- Birden fazla aday varsa action "ask_user" ve speak bir netleştirme sorusu olsun.
- Hedef bir yazı, numara veya tabelaysa ve görünüyorsa action "read_text" ve box yazının bölgesi olsun.
- Kullanıcı "önümde ne var" diye sorarsa action "whats_ahead": önce olası engeller (basamak, direk, kapı kenarı), sonra yön.
- Yolun güvenli olduğunu ASLA söyleme. "Güvenli", "geçebilirsin", "engel yok" deme; sadece gördüğünü söyle.
- Karşıdan karşıya geçme ve trafik ışığı kararı verme. İlaç, doz veya sağlık bilgisi okuma.
- Emin değilsen bunu söyle ve kullanıcıdan telefonu yavaşça hareket ettirmesini iste.
"""

READER_INSTRUCTIONS = (
    "Görüntüdeki yazıyı veya numarayı aynen oku. Sadece okuduğunu Türkçe tek kısa cümleyle söyle. "
    "Okunamıyorsa 'Okuyamadım' de. İlaç veya doz bilgisi okuma."
)

_REFUSALS = [
    (
        re.compile(r"karşıya geç|karşıdan karşıya|geçebilir miyim|trafik ışığı|ışık yeşil", re.I),
        "Karşıdan karşıya geçme kararını ben veremem. Bu kararı sen ver veya birinden yardım iste.",
    ),
    (
        re.compile(r"ilaç|doz|hap|reçete", re.I),
        "İlaç ve doz bilgisi okumuyorum. Lütfen bir eczacıya veya yakınına danış.",
    ),
]

_UNSAFE_CLAIM = re.compile(r"[^.!?]*(güvenli|geçebilirsin|engel yok|tehlike yok)[^.!?]*[.!?]?", re.I)
_SAFE_REPLACEMENT = "Gördüğümü söyleyebilirim ama yolun güvenli olduğuna ben karar veremem."


def scrub(text: str) -> str:
    """Remove any sentence that claims the path is safe."""
    cleaned = _UNSAFE_CLAIM.sub("", text).strip()
    if cleaned != text.strip():
        cleaned = f"{cleaned} {_SAFE_REPLACEMENT}".strip()
    return cleaned


@dataclass
class Session:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    goal: str = ""
    steps: int = 0
    awaiting_reply: bool = False
    user_reply: str = ""
    history: list[str] = field(default_factory=list)
    last_seen: dict[str, str] = field(default_factory=dict)


@dataclass
class StepResult:
    speak: str
    done: bool
    action: str
    box: list[float] | None
    trace: list[dict]
    awaiting_reply: bool = False


class Agent:
    def __init__(self, client: MetaClient):
        self.client = client

    # --- planning -----------------------------------------------------------

    def _plan(self, session: Session, frame: bytes) -> dict:
        if self.client.settings.mock:
            return mock_plan(session)
        memory = "; ".join(f"{k}: {v}" for k, v in session.last_seen.items()) or "yok"
        recent = " | ".join(session.history[-4:]) or "yok"
        prompt = (
            f"Hedef: {session.goal}\n"
            f"Kullanıcının son cevabı: {session.user_reply or 'yok'}\n"
            f"Son adımlar: {recent}\n"
            f"Hafıza (son görülen yönler): {memory}\n"
            "Bu kare için bir sonraki eylemi JSON olarak ver."
        )
        return parse_json(self.client.spark(PLANNER_INSTRUCTIONS, prompt, [frame]))

    def _read(self, crop: bytes) -> str:
        if self.client.settings.mock:
            return "Tabelada 512 Kızılay yazıyor."
        return self.client.spark(READER_INSTRUCTIONS, "Bu kırpılmış görüntüdeki yazıyı oku.", [crop])

    # --- one step ---------------------------------------------------------------

    def step(self, session: Session, frame: bytes) -> StepResult:
        trace: list[dict] = []

        for pattern, message in _REFUSALS:
            if pattern.search(session.goal) or pattern.search(session.user_reply):
                trace.append({"tool": "guard", "detail": "kapsam dışı istek reddedildi", "ms": 0})
                return StepResult(message, True, "refuse", None, trace)

        session.steps += 1
        if session.steps > MAX_STEPS:
            msg = "Hedefi bulamadım. Başka bir yöne dönüp yeniden deneyebilir veya birinden yardım isteyebilirsin."
            return StepResult(msg, True, "give_up", None, trace)

        t0 = time.perf_counter()
        plan = self._plan(session, frame)
        trace.append({"tool": "plan", "detail": plan, "ms": _ms(t0)})
        session.user_reply = ""

        action = plan.get("action", "locate")
        target = (plan.get("target") or session.goal).strip()
        box = plan.get("box")
        speak = plan.get("speak") or ""
        done = False
        awaiting = False

        if action == "locate" and box:
            box = list(geometry.clamp_box(box))
            direction, dist = geometry.clock_direction(box), geometry.distance(box)
            session.last_seen[target] = direction
            speak = f"{target.capitalize()} {direction} yönünde, {dist}."
            if geometry.is_reached(box):
                speak += " Hedefin hemen önünde olmalı; elinle dikkatlice kontrol et."
                done = True
            trace.append({"tool": "direction", "detail": f"{direction}, {dist}", "ms": 0})
        elif action == "read_text" and box:
            box = list(geometry.clamp_box(box))
            t1 = time.perf_counter()
            try:
                speak = self._read(geometry.crop_jpeg(frame, box)).strip()
                done = True
            except OSError:
                speak = "Görüntüyü işleyemedim. Telefonu sabit tutup tekrar dene."
            trace.append({"tool": "read_text", "detail": speak, "ms": _ms(t1)})
        elif action == "ask_user":
            awaiting = True
        elif action in ("whats_ahead", "done"):
            done = True
        else:
            box = None
            speak = speak or "Göremedim. Telefonu yavaşça sağa çevir."

        speak = scrub(speak)
        session.awaiting_reply = awaiting
        session.history.append(f"{action}: {speak}")
        return StepResult(speak, done, action, box, trace, awaiting)


class SessionStore:
    def __init__(self, limit: int = 200):
        self._sessions: dict[str, Session] = {}
        self._limit = limit

    def get_or_create(self, session_id: str | None) -> Session:
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        if len(self._sessions) >= self._limit:
            self._sessions.pop(next(iter(self._sessions)))
        session = Session()
        self._sessions[session.id] = session
        return session


def _ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def mock_plan(session: Session) -> dict:
    """Scripted planner output so the full loop can be exercised without the API."""
    goal = session.goal.lower()
    n = session.steps
    if re.search(r"oku|numara|yazı|tabela|otobüs", goal):
        if n == 1:
            return {"action": "locate", "target": "tabela", "box": None,
                    "speak": "Yazı göremiyorum. Telefonu biraz yukarı kaldır."}
        return {"action": "read_text", "target": "tabela", "box": [300, 200, 700, 420], "speak": ""}
    if re.search(r"önümde|ne var", goal):
        return {"action": "whats_ahead", "target": "önü",
                "speak": "Hemen önünde olası bir basamak var, dikkat. Saat 1 yönünde bir kapı görünüyor."}
    if n == 1:
        return {"action": "locate", "target": "kapı", "box": None,
                "speak": "Henüz göremiyorum. Telefonu yavaşça sağa çevir."}
    if n == 2 and not session.history[-1].startswith("ask_user"):
        return {"action": "ask_user", "target": "kapı", "box": None,
                "speak": "İki kapı görüyorum. Sağdaki mi, soldaki mi?"}
    if n == 3:
        return {"action": "locate", "target": "kapı", "box": [640, 250, 840, 700], "speak": ""}
    return {"action": "locate", "target": "kapı", "box": [400, 80, 640, 960], "speak": ""}
