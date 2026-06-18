from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Iterable, Sequence

from bot.services.harmonic_mixing import transition_score
from analysis.camelot import camelot_compatible

MOOD_PROFILES = {
    "warm-up": {"energy": 0.42, "min_bpm": 110, "max_bpm": 122},
    "peak time": {"energy": 0.82, "min_bpm": 122, "max_bpm": 132},
    "afterhours": {"energy": 0.58, "min_bpm": 115, "max_bpm": 126},
    "chill": {"energy": 0.3, "min_bpm": 98, "max_bpm": 118},
}

RNG = random.SystemRandom()
BPM_COMPATIBILITY_TOLERANCE = 2.3
KEY_ZONE_BLOCK_SIZE = 8
KEY_ZONE_SHIFT = 5
KEY_ZONE_WIDTH = 3


@dataclass(slots=True)
class PlaylistResult:
    tracks: list
    total_duration_sec: int
    actual_duration_sec: int
    commentary: str


def generate_dj_playlist(
    tracks: Sequence,
    target_duration_minutes: int,
    mood: str = "warm-up",
    *,
    strict_key_progression: bool = False,
) -> PlaylistResult:
    mood_profile = MOOD_PROFILES.get(mood, MOOD_PROFILES["warm-up"])
    candidates = [
        track
        for track in tracks
        if getattr(track, "bpm", None) is not None
        and getattr(track, "camelot_key", None)
        and getattr(track, "duration_sec", None)
        and getattr(track, "is_suitable", True)
    ]
    if not candidates:
        return PlaylistResult(
            [],
            0,
            0,
            "Извините, пока нет больше подборок в этом БПМ диапазоне.\n"
            "Заходите позже.... 😔",
        )

    RNG.shuffle(candidates)
    candidates.sort(
        key=lambda item: (
            abs((item.energy_level or 0) - mood_profile["energy"]),
            abs((item.bpm or 0) - ((mood_profile["min_bpm"] + mood_profile["max_bpm"]) / 2)),
        )
    )
    selected = [_pick_start_track(candidates)]
    candidates.remove(selected[0])
    candidates = _filter_candidates_for_bpm_family(candidates, selected[0])
    anchor_camelot_key = getattr(selected[0], "camelot_key", None)
    target_duration_sec = target_duration_minutes * 60
    effective_duration = _effective_track_duration_sec(selected[0])
    actual_duration = int(selected[0].duration_sec or 0)
    used_relaxed_key_transition = False

    while candidates and effective_duration < target_duration_sec:
        current = selected[-1]
        preferred_key_window = _preferred_key_window(anchor_camelot_key, len(selected))
        next_track, used_relaxed_key_now = _pick_next_track(
            current,
            candidates,
            mood_profile["energy"],
            strict_key_progression=strict_key_progression,
            allow_relaxed_key=not used_relaxed_key_transition,
            preferred_key_window=preferred_key_window,
        )
        if next_track is None:
            break
        candidates.remove(next_track)
        used_relaxed_key_transition = used_relaxed_key_transition or used_relaxed_key_now
        next_effective_duration = _effective_track_duration_sec(next_track)
        projected_effective_duration = effective_duration + next_effective_duration
        if projected_effective_duration > target_duration_sec * 1.1 and selected:
            continue
        selected.append(next_track)
        effective_duration = projected_effective_duration
        actual_duration += int(next_track.duration_sec or 0)

    commentary = (
        "Тайминг считается по правилу 50% длины трека: в сет идет половина длительности "
        "каждого выбранного трека, а порядок собирается заново под совместимость BPM и тональности."
    )
    return PlaylistResult(selected, effective_duration, actual_duration, commentary)


def _effective_track_duration_sec(track) -> int:
    duration_sec = int(getattr(track, "duration_sec", 0) or 0)
    return max(1, duration_sec // 2) if duration_sec else 0


def _pick_start_track(candidates: Sequence):
    top_pool_size = min(12, len(candidates))
    return RNG.choice(list(candidates[:top_pool_size]))


def _filter_candidates_for_bpm_family(candidates: Sequence, start_track):
    if getattr(start_track, "bpm", None) is None:
        return list(candidates)
    filtered = [track for track in candidates if _bpm_compatible(start_track, track, tolerance=8.0)]
    if len(filtered) >= 10:
        return filtered
    filtered = [track for track in candidates if _bpm_compatible(start_track, track, tolerance=12.0)]
    if len(filtered) >= 10:
        return filtered
    return list(candidates)


def _pick_next_track(
    current,
    candidates: Iterable,
    target_energy: float,
    *,
    strict_key_progression: bool,
    allow_relaxed_key: bool,
    preferred_key_window: set[str] | None,
):
    candidate_list = list(candidates)
    narrowed_candidates = [track for track in candidate_list if _bpm_compatible(current, track, tolerance=6.0)]
    if len(narrowed_candidates) < 4:
        narrowed_candidates = [track for track in candidate_list if _bpm_compatible(current, track, tolerance=10.0)]
    if not narrowed_candidates:
        narrowed_candidates = [track for track in candidate_list if _bpm_compatible(current, track, tolerance=12.0)]
    if not narrowed_candidates:
        return None, False

    if preferred_key_window:
        preferred_candidates = [
            track
            for track in narrowed_candidates
            if getattr(track, "camelot_key", None) in preferred_key_window
        ]
        if preferred_candidates:
            narrowed_candidates = preferred_candidates

    used_relaxed_key_now = False
    if strict_key_progression:
        compatible_key_candidates = [track for track in narrowed_candidates if _key_compatible(current, track)]
        if compatible_key_candidates:
            narrowed_candidates = compatible_key_candidates
        elif allow_relaxed_key:
            used_relaxed_key_now = True
        else:
            return None, False

    scored_tracks = []
    for track in narrowed_candidates:
        score = transition_score(
            current_bpm=getattr(current, "bpm", None),
            next_bpm=getattr(track, "bpm", None),
            current_key=getattr(current, "camelot_key", None),
            next_key=getattr(track, "camelot_key", None),
            current_energy=getattr(current, "energy_level", None),
            next_energy=getattr(track, "energy_level", None),
            target_energy=target_energy,
        )
        bpm_distance = _bpm_distance(current, track)
        score -= min(4.0, bpm_distance / 2)
        if getattr(track, "bpm", 0) < getattr(current, "bpm", 0) - 2:
            score -= 2
        scored_tracks.append((score, track))

    if not scored_tracks:
        return None

    scored_tracks.sort(key=lambda item: item[0], reverse=True)
    top_pool_size = min(8, len(scored_tracks))
    top_pool = scored_tracks[:top_pool_size]
    max_score = top_pool[0][0]
    weighted_tracks = []
    for score, track in top_pool:
        weight = max(1, int((score - max_score + 3) * 10))
        weighted_tracks.extend([track] * weight)
    return RNG.choice(weighted_tracks), used_relaxed_key_now


def _key_compatible(current, next_track) -> bool:
    current_key = getattr(current, "camelot_key", None)
    next_key = getattr(next_track, "camelot_key", None)
    if not current_key or not next_key:
        return False
    return current_key == next_key or camelot_compatible(current_key, next_key)


def _preferred_key_window(anchor_camelot_key: str | None, selected_count: int) -> set[str] | None:
    if not anchor_camelot_key:
        return None
    if selected_count < KEY_ZONE_BLOCK_SIZE:
        return None

    parsed = _parse_camelot_key(anchor_camelot_key)
    if parsed is None:
        return None

    number, mode = parsed
    block_index = selected_count // KEY_ZONE_BLOCK_SIZE
    start_number = ((number - 1) + (block_index * KEY_ZONE_SHIFT)) % 12 + 1
    return {
        f"{((start_number - 1 + offset) % 12) + 1}{mode}"
        for offset in range(KEY_ZONE_WIDTH)
    }


def _parse_camelot_key(value: str | None) -> tuple[int, str] | None:
    if not value or len(value) < 2:
        return None
    try:
        return int(value[:-1]), value[-1]
    except ValueError:
        return None


def _bpm_distance(current, next_track) -> float:
    current_bpm = getattr(current, "bpm", None)
    next_bpm = getattr(next_track, "bpm", None)
    if current_bpm is None or next_bpm is None:
        return 999.0
    current_options = _bpm_variants(float(current_bpm))
    next_options = _bpm_variants(float(next_bpm))
    return min(abs(a - b) for a in current_options for b in next_options)


def _bpm_compatible(current, next_track, *, tolerance: float) -> bool:
    return _bpm_distance(current, next_track) <= tolerance


def _bpm_variants(bpm: float) -> list[float]:
    variants = [bpm]
    if bpm >= 120 - BPM_COMPATIBILITY_TOLERANCE:
        variants.append(bpm / 2)
    if bpm <= 100 + BPM_COMPATIBILITY_TOLERANCE:
        variants.append(bpm * 2)
    return variants
