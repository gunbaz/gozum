"""Smoke-test the real Meta Model API calls Gözüm depends on.

Usage:
    uv run python scripts/smoke.py text           # auth + plain text
    uv run python scripts/smoke.py plan IMAGE     # planner JSON on a photo
    uv run python scripts/smoke.py read IMAGE     # text reading on a photo
    uv run python scripts/smoke.py asr WAV        # speech-to-text

Each call costs a fraction of a cent. Prints latency so we can report it.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from server.agent import PLANNER_INSTRUCTIONS, READER_INSTRUCTIONS  # noqa: E402
from server.meta_client import MetaClient, Settings, parse_json  # noqa: E402


def main() -> None:
    settings = Settings.from_env()
    if settings.mock:
        sys.exit("MODEL_API_KEY is empty or MOCK=1; nothing to test.")
    client = MetaClient(settings)
    mode = sys.argv[1] if len(sys.argv) > 1 else "text"
    arg = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    t0 = time.perf_counter()
    if mode == "text":
        out = client.spark("Kısa cevap ver.", "Türkiye'nin başkenti neresi? Tek kelime.")
    elif mode == "plan":
        out = client.spark(
            PLANNER_INSTRUCTIONS,
            "Hedef: kapıyı bul\nKullanıcının son cevabı: yok\nSon adımlar: yok\n"
            "Hafıza: yok\nBu kare için bir sonraki eylemi JSON olarak ver.",
            [arg.read_bytes()],
        )
        print("parsed:", parse_json(out))
    elif mode == "read":
        out = client.spark(READER_INSTRUCTIONS, "Bu görüntüdeki yazıyı oku.", [arg.read_bytes()])
    elif mode == "asr":
        out = client.transcribe(arg.read_bytes())
    else:
        sys.exit(f"unknown mode {mode}")
    print(f"[{mode}] {int((time.perf_counter() - t0) * 1000)} ms")
    print(out)


if __name__ == "__main__":
    main()
