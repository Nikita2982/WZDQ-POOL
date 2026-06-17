from types import SimpleNamespace

from scanner.scan_tracks import ChannelScanner


def _message(message_id: int, text: str):
    return SimpleNamespace(id=message_id, message=text, file=None)


def _audio_message(message_id: int, text: str):
    return SimpleNamespace(
        id=message_id,
        message=text,
        file=SimpleNamespace(mime_type="audio/mpeg"),
    )


def test_ignored_section_breaks_previous_supported_section():
    scanner = ChannelScanner.__new__(ChannelScanner)
    scanner.settings = SimpleNamespace(
        supported_genres=["electronic", "beatport_top_10", "house"],
        genre_hashtag_prefix="#",
    )

    sections = ChannelScanner._build_sections(
        scanner,
        [
            _message(1, "#electronic"),
            _message(2, ""),
            _message(3, "#beatport_top_10"),
            _message(4, ""),
            _message(5, "#house"),
            _message(6, ""),
        ],
    )

    assert [(section.genre, section.start_index, section.end_index) for section in sections] == [
        ("electronic", 0, 2),
        (None, 2, 4),
        ("house", 4, 6),
    ]


def test_text_message_with_hashtag_breaks_previous_section():
    scanner = ChannelScanner.__new__(ChannelScanner)
    scanner.settings = SimpleNamespace(
        supported_genres=["weekly_update_electronic", "soundcloud_selects"],
        genre_hashtag_prefix="#",
    )

    sections = ChannelScanner._build_sections(
        scanner,
        [
            _message(1, "#weekly_update_electronic"),
            _audio_message(2, ""),
            _message(3, "Soundcloud selected #lossless"),
            _audio_message(4, ""),
        ],
    )

    assert [(section.genre, section.start_index, section.end_index) for section in sections] == [
        (None, 0, 2),
        (None, 2, 4),
    ]


def test_audio_caption_hashtag_is_not_section_boundary():
    scanner = ChannelScanner.__new__(ChannelScanner)
    scanner.settings = SimpleNamespace(
        supported_genres=["electronic", "lossless"],
        genre_hashtag_prefix="#",
    )

    sections = ChannelScanner._build_sections(
        scanner,
        [
            _message(1, "#electronic"),
            _audio_message(2, "Track caption #lossless"),
            _audio_message(3, ""),
        ],
    )

    assert [(section.genre, section.start_index, section.end_index) for section in sections] == [
        ("electronic", 0, 3),
    ]
