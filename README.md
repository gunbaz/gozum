# Gözüm

**A Turkish-language find-and-guide agent for blind and low-vision people**, built for the Meta Global AI Developer Hackathon (Indie track, theme: *Build for Your World*).

> Gözüm is a wayfinding aid. It does **not** replace a white cane, a guide dog or a person, and it never tells you a path is safe.

## What it does

You tap the big button and say a goal, e.g. *"Çıkış kapısını bul"* (find the exit door) or *"Otobüsün numarasını oku"* (read the bus number). Gözüm then runs a multi-step agent loop over camera frames:

1. **Plan** – Muse Spark looks at the frame and picks the next action as JSON: `locate`, `read_text`, `ask_user`, `whats_ahead` or `done`.
2. **Act** – the server executes it:
   - `locate` → converts the model's box into clock-face directions and coarse distance (*"Kapı saat 1 yönünde, orta mesafede"*)
   - `read_text` → crops the region at full resolution and asks Muse Spark to read it
   - `ask_user` → asks a clarifying question (*"İki kapı görüyorum, sağdaki mi soldaki mi?"*) and waits for a spoken answer
3. **Repeat** every ~2.5 s until the target is reached, then stop.

Design choices:
- **Stop–scan–move, not continuous hazard radar.** Model latency is seconds, so Gözüm guides you step by step instead of claiming real-time collision warnings.
- **Clock-face directions** (the convention used in orientation & mobility training) and coarse distance (near / medium / far), never metres.
- **Safety guards:** refuses street-crossing decisions and medicine/dose reading; strips any "safe / you can cross" claim from model output.
- **Accessibility:** output goes to an `aria-live` region (read by TalkBack/VoiceOver) and to Turkish speech synthesis; one large button; wake lock.

## Meta models used

| Model | Role |
|---|---|
| Muse Spark (`muse-spark-1.3`) | planner, perception grounding, text reading |
| Muse Voice Transcribe | spoken goals and answers (16 kHz WAV recorded in the browser) |
| SAM 3.1 | *planned:* target segmentation overlay |

## Run locally

```bash
uv sync
cp .env.example .env    # leave MODEL_API_KEY empty for mock mode
uv run uvicorn server.main:app --reload --port 8000
```

Without a key the app runs in **mock mode** (red MOCK badge, scripted agent replies, no API calls). To test on a phone (camera needs HTTPS):

```bash
cloudflared tunnel --url http://localhost:8000
```

Tests: `uv run pytest`

## Privacy

Camera frames and audio are processed in memory and sent only to Meta Model API (standard mode, not contributor mode). Nothing is stored or logged.

## Built during the hackathon

All code in this repository was written during the event (Oct 26 – Nov 4, 2026); see the commit history. Development was AI-assisted.

## License

MIT
