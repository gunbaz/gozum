"""Turn model coordinates into spoken Turkish directions.

Boxes use Muse Spark's normalized grid: [x0, y0, x1, y1] in 0..1000,
origin at the top-left of the frame.
"""

from __future__ import annotations

from io import BytesIO

from PIL import Image

Box = tuple[float, float, float, float]

# A phone camera sees roughly 60-70 degrees horizontally, so only the hours
# around 12 are reachable. Five bins keep the guidance coarse on purpose.
_CLOCK_BINS = [(150, "saat 10"), (380, "saat 11"), (620, "saat 12"), (850, "saat 1")]


def clamp_box(box: Box) -> Box:
    x0, y0, x1, y1 = (min(max(float(v), 0.0), 1000.0) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def clock_direction(box: Box) -> str:
    x0, _, x1, _ = clamp_box(box)
    cx = (x0 + x1) / 2
    for limit, label in _CLOCK_BINS:
        if cx < limit:
            return label
    return "saat 2"


def distance(box: Box) -> str:
    """Coarse distance from apparent size and how low the object sits."""
    x0, y0, x1, y1 = clamp_box(box)
    area = (x1 - x0) * (y1 - y0) / 1_000_000
    if area > 0.25 or y1 > 900:
        return "yakın"
    if area > 0.06:
        return "orta mesafede"
    return "uzakta"


def is_reached(box: Box) -> bool:
    return clock_direction(box) == "saat 12" and distance(box) == "yakın"


def crop_jpeg(jpeg: bytes, box: Box, pad: float = 0.08) -> bytes:
    """Crop a region (with padding) so a second model call can read details."""
    img = Image.open(BytesIO(jpeg))
    w, h = img.size
    x0, y0, x1, y1 = clamp_box(box)
    px, py = (x1 - x0) * pad, (y1 - y0) * pad
    left = int(max(0, (x0 - px) / 1000 * w))
    top = int(max(0, (y0 - py) / 1000 * h))
    right = int(min(w, (x1 + px) / 1000 * w))
    bottom = int(min(h, (y1 + py) / 1000 * h))
    out = BytesIO()
    img.crop((left, top, max(right, left + 1), max(bottom, top + 1))).convert("RGB").save(
        out, format="JPEG", quality=90
    )
    return out.getvalue()
