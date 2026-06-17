from scanner.metadata_reader import (
    canonicalize_genre,
    extract_section_header_genre_from_text,
)


def test_weekly_update_electronic_is_ignored():
    assert canonicalize_genre("weekly_update_electronic") is None
    assert (
        extract_section_header_genre_from_text(
            "#weekly_update_electronic",
            supported_genres=["weekly_update_electronic"],
        )
        is None
    )


def test_weekly_update_rap_still_maps_to_rap():
    assert canonicalize_genre("weekly_update_rap") == "rap"
    assert (
        extract_section_header_genre_from_text(
            "#weekly_update_rap",
            supported_genres=["weekly_update_rap"],
        )
        == "rap"
    )
