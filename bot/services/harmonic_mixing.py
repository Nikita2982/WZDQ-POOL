from __future__ import annotations

from analysis.camelot import camelot_compatible


def transition_score(
    *,
    current_bpm: float | None,
    next_bpm: float | None,
    current_key: str | None,
    next_key: str | None,
    current_energy: float | None,
    next_energy: float | None,
    target_energy: float,
) -> float:
    score = 0.0

    if camelot_compatible(current_key, next_key):
        score += 5.0
    elif current_key == next_key:
        score += 4.0

    if current_bpm is not None and next_bpm is not None:
        bpm_gap = abs(next_bpm - current_bpm)
        score += max(0.0, 3.0 - min(bpm_gap, 6.0) / 2)

    if current_energy is not None and next_energy is not None:
        growth_penalty = abs((next_energy - current_energy) - 0.08)
        score += max(0.0, 2.5 - growth_penalty * 4)
        score += max(0.0, 1.5 - abs(next_energy - target_energy) * 2)

    return score
