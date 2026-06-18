from dataclasses import dataclass

import bot.services.playlist_generator as playlist_generator
from analysis.camelot import camelot_compatible
from bot.services.playlist_generator import generate_dj_playlist


@dataclass
class StubTrack:
    id: int
    genre: str
    artist: str
    title: str
    duration_sec: int
    bpm: float
    camelot_key: str
    energy_level: float
    is_suitable: bool = True


def test_generate_dj_playlist_returns_sorted_mixable_tracks(monkeypatch):
    monkeypatch.setattr(playlist_generator, "RNG", __import__("random").Random(0))
    tracks = [
        StubTrack(1, "afro_house", "A", "One", 360, 118, "8A", 0.40),
        StubTrack(2, "afro_house", "B", "Two", 350, 119, "9A", 0.48),
        StubTrack(3, "afro_house", "C", "Three", 380, 121, "10A", 0.57),
    ]

    result = generate_dj_playlist(
        tracks,
        target_duration_minutes=12,
        mood="warm-up",
        strict_key_progression=True,
    )

    assert len(result.tracks) >= 2
    for current, next_track in zip(result.tracks, result.tracks[1:]):
        assert camelot_compatible(current.camelot_key, next_track.camelot_key) or current.camelot_key == next_track.camelot_key


def test_generate_dj_playlist_allows_only_one_relaxed_key_transition_when_needed(monkeypatch):
    monkeypatch.setattr(playlist_generator, "RNG", __import__("random").Random(0))
    tracks = [
        StubTrack(1, "electronic", "A", "One", 360, 120, "8A", 0.40),
        StubTrack(2, "electronic", "B", "Two", 360, 121, "9A", 0.48),
        StubTrack(3, "electronic", "C", "Three", 360, 122, "1B", 0.52),
        StubTrack(4, "electronic", "D", "Four", 360, 123, "4B", 0.58),
    ]

    result = generate_dj_playlist(
        tracks,
        target_duration_minutes=12,
        mood="warm-up",
        strict_key_progression=True,
    )

    incompatible_transitions = 0
    for current, next_track in zip(result.tracks, result.tracks[1:]):
        if not (camelot_compatible(current.camelot_key, next_track.camelot_key) or current.camelot_key == next_track.camelot_key):
            incompatible_transitions += 1

    assert len(result.tracks) >= 3
    assert incompatible_transitions == 1


def test_generate_dj_playlist_rotates_preferred_key_zone_every_eight_tracks(monkeypatch):
    monkeypatch.setattr(playlist_generator, "RNG", __import__("random").Random(0))
    monkeypatch.setattr(playlist_generator, "_pick_start_track", lambda candidates: candidates[0])
    tracks = [
        StubTrack(1, "electronic", "A", "One", 300, 120, "8A", 0.40),
        StubTrack(2, "electronic", "B", "Two", 300, 120, "9A", 0.41),
        StubTrack(3, "electronic", "C", "Three", 300, 121, "10A", 0.42),
        StubTrack(4, "electronic", "D", "Four", 300, 121, "8A", 0.43),
        StubTrack(5, "electronic", "E", "Five", 300, 122, "9A", 0.44),
        StubTrack(6, "electronic", "F", "Six", 300, 122, "10A", 0.45),
        StubTrack(7, "electronic", "G", "Seven", 300, 121, "8A", 0.46),
        StubTrack(8, "electronic", "H", "Eight", 300, 120, "10A", 0.47),
        StubTrack(9, "electronic", "I", "Nine", 300, 121, "1A", 0.48),
        StubTrack(10, "electronic", "J", "Ten", 300, 121, "2A", 0.49),
    ]

    result = generate_dj_playlist(tracks, target_duration_minutes=45, mood="warm-up")

    assert len(result.tracks) >= 9
    assert result.tracks[8].camelot_key in {"1A", "2A", "3A"}


def test_generate_dj_playlist_does_not_hard_limit_pool_to_start_track_family(monkeypatch):
    monkeypatch.setattr(playlist_generator, "RNG", __import__("random").Random(0))
    monkeypatch.setattr(playlist_generator, "_pick_start_track", lambda candidates: candidates[0])
    tracks = [
        StubTrack(1, "electronic", "A", "One", 300, 118, "8A", 0.40),
        StubTrack(2, "electronic", "B", "Two", 300, 121, "9A", 0.42),
        StubTrack(3, "electronic", "C", "Three", 300, 124, "10A", 0.44),
        StubTrack(4, "electronic", "D", "Four", 300, 127, "11A", 0.46),
        StubTrack(5, "electronic", "E", "Five", 300, 130, "12A", 0.48),
    ]

    result = generate_dj_playlist(tracks, target_duration_minutes=20, mood="warm-up")

    assert len(result.tracks) >= 4
