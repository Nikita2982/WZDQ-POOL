from __future__ import annotations

from bot.services.playlist_generator import PlaylistResult


SECTION_TITLES = {
    "electronic": "Electronic",
    "house": "House",
    "rap": "Rap",
    "dance_pop": "Dance / Pop",
}


def format_playlist_response(genre: str, duration: int, result: PlaylistResult) -> str:
    if not result.tracks:
        return result.commentary

    lines = [
        "<b>Сет готов</b>",
        f"Раздел: {SECTION_TITLES.get(genre, genre.replace('_', ' ').title())}",
        f"Выбранный тайминг: {duration} мин",
        f"Треков в выдаче: {len(result.tracks)}",
        "",
        "Тайминг считается по правилу 50% длины каждого трека.",
        f"Эффективная длительность: {round(result.total_duration_sec / 60, 1)} мин",
        f"Фактическая длина всех файлов: {round(result.actual_duration_sec / 60, 1)} мин",
        "",
    ]
    for index, track in enumerate(result.tracks, start=1):
        duration_min = round((track.duration_sec or 0) / 60, 1)
        effective_duration_min = round((track.duration_sec or 0) / 120, 1)
        artist = track.artist or "Unknown Artist"
        lines.append(
            f"{index}. {artist} - {track.title} | {track.bpm} BPM | "
            f"{track.camelot_key} | {duration_min} мин файла | {effective_duration_min} мин в тайминге"
        )
    lines.extend(["", result.commentary])
    return "\n".join(lines)
