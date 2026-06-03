from __future__ import annotations

import re

GENRE_ALIAS_MAP = {
    "uk_warm": "electronic",
    "uk_prime": "electronic",
    "dubstep": "electronic",
    "techno": "electronic",
    "jercey": "electronic",
    "jersey": "electronic",
    "break": "electronic",
    "baile": "electronic",
    "dnb": "electronic",
    "edits_remixes": "electronic",
    "bandcamp": "electronic",
    "soundcloud_selects": "electronic",
    "ru_rap_intro": "rap",
    "en_rap_intro": "rap",
    "weekly_update_rap": "rap",
    "weekly_update_electronic": "electronic",
    "tech": "house",
    "bass": "house",
    "afro": "house",
    "house_remixes": "house",
}

IGNORED_SECTION_TAGS = {
    "acapella",
    "samples",
    "scratch",
    "disco",
    "en_intro",
    "tools",
    "beatport_top_10",
    "soundcloud_reels",
}


def canonicalize_genre(genre: str | None) -> str | None:
    if genre is None:
        return None
    if genre in IGNORED_SECTION_TAGS:
        return None
    return GENRE_ALIAS_MAP.get(genre, genre)


def extract_genre_from_text(
    text: str | None,
    *,
    supported_genres: list[str],
    hashtag_prefix: str = "#",
) -> str | None:
    if not text:
        return None

    normalized = text.lower()
    for genre in supported_genres:
        hashtag = f"{hashtag_prefix}{genre}"
        if hashtag in normalized:
            return canonicalize_genre(genre)

    tags = re.findall(r"#([a-z0-9_]+)", normalized)
    for tag in tags:
        if tag in supported_genres:
            return canonicalize_genre(tag)
    return None


def extract_section_header_genre_from_text(
    text: str | None,
    *,
    supported_genres: list[str],
    hashtag_prefix: str = "#",
) -> str | None:
    if not text:
        return None

    normalized = text.strip().lower()
    match = re.fullmatch(r"#([a-z0-9_]+)", normalized)
    if not match:
        return None

    tag = match.group(1)
    if tag in supported_genres:
        return canonicalize_genre(tag)
    return None


def extract_section_header_tag(text: str | None) -> str | None:
    if not text:
        return None
    normalized = text.strip().lower()
    match = re.fullmatch(r"#([a-z0-9_]+)", normalized)
    if not match:
        return None
    return match.group(1)


def build_message_link(chat_username: str | None, message_id: int) -> str | None:
    if not chat_username:
        return None
    username = chat_username.lstrip("@")
    return f"https://t.me/{username}/{message_id}"
