from types import SimpleNamespace

from scanner.scan_tracks import ChannelScanner


def _message(message_id: int, text: str):
    return SimpleNamespace(id=message_id, message=text)


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
