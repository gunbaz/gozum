from io import BytesIO

from PIL import Image

from server import geometry


def test_clock_direction_bins():
    assert geometry.clock_direction((0, 0, 100, 100)) == "saat 10"
    assert geometry.clock_direction((450, 0, 550, 100)) == "saat 12"
    assert geometry.clock_direction((700, 0, 800, 100)) == "saat 1"
    assert geometry.clock_direction((900, 0, 1000, 100)) == "saat 2"


def test_distance_from_size_and_position():
    assert geometry.distance((450, 450, 520, 520)) == "uzakta"
    assert geometry.distance((300, 300, 600, 600)) == "orta mesafede"
    assert geometry.distance((100, 100, 900, 900)) == "yakın"
    assert geometry.distance((480, 800, 520, 950)) == "yakın"  # low in frame = close


def test_clamp_handles_swapped_and_out_of_range():
    assert geometry.clamp_box((1200, -5, 100, 300)) == (100.0, 0.0, 1000.0, 300.0)


def test_crop_returns_smaller_jpeg():
    buf = BytesIO()
    Image.new("RGB", (800, 600), "white").save(buf, format="JPEG")
    crop = Image.open(BytesIO(geometry.crop_jpeg(buf.getvalue(), (250, 250, 500, 500))))
    assert crop.width < 800 and crop.height < 600
