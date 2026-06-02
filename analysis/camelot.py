from __future__ import annotations

CAMELot_MAP = {
    "C Major": "8B",
    "G Major": "9B",
    "D Major": "10B",
    "A Major": "11B",
    "E Major": "12B",
    "B Major": "1B",
    "F# Major": "2B",
    "C# Major": "3B",
    "Ab Major": "4B",
    "Eb Major": "5B",
    "Bb Major": "6B",
    "F Major": "7B",
    "A Minor": "8A",
    "E Minor": "9A",
    "B Minor": "10A",
    "F# Minor": "11A",
    "C# Minor": "12A",
    "G# Minor": "1A",
    "D# Minor": "2A",
    "Bb Minor": "3A",
    "F Minor": "4A",
    "C Minor": "5A",
    "G Minor": "6A",
    "D Minor": "7A",
}


def musical_key_to_camelot(musical_key: str | None) -> str | None:
    if not musical_key:
        return None
    return CAMELot_MAP.get(musical_key)


def camelot_compatible(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    left_num = int(left[:-1])
    left_mode = left[-1]
    right_num = int(right[:-1])
    right_mode = right[-1]
    same_mode_step = {(left_num % 12) + 1, (left_num - 2) % 12 + 1}
    return (right_num == left_num and right_mode != left_mode) or (
        right_mode == left_mode and right_num in same_mode_step
    )
