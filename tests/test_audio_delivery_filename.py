from types import SimpleNamespace

from bot.services.audio_delivery import AudioDeliveryService


def test_original_filename_strips_numeric_prefix_from_raw_metadata():
    track = SimpleNamespace(
        artist="Sunburn",
        title="SEXY BACK SUNBURN EDIT",
        raw_metadata={"file_name": "1083_SEXY BACK SUNBURN EDIT - SUNBURN.mp3"},
    )

    filename = AudioDeliveryService._original_filename(track, 1083, None)

    assert filename == "SEXY BACK SUNBURN EDIT - SUNBURN.mp3"


def test_original_filename_strips_numeric_prefix_from_title_fallback():
    track = SimpleNamespace(
        artist="Trizha Harun",
        title="1077_POP DAT THANG",
        raw_metadata={},
    )

    filename = AudioDeliveryService._original_filename(track, 1077, None)

    assert filename == "Trizha Harun - POP DAT THANG.mp3"
