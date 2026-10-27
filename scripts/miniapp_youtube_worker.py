"""JSON-lines bridge to the existing, separately installed YouTube analyser."""
import asyncio
import json
import logging
from pathlib import Path
import re
import signal
import sys


def emit(kind, **data):
    print(json.dumps({"type": kind, **data}, ensure_ascii=False), flush=True)


def report_tracks(report):
    tracks = []
    for line in report.splitlines():
        match = re.match(r"^\d+ · (.+?) — (.+?)(?:  \[(\d{2,}:\d{2}:\d{2})\])?$", line)
        if match:
            tracks.append({"artist": match[1], "title": match[2], "timestamp": match[3]})
    return tracks


async def run():
    project = Path(sys.argv[1]).resolve()
    sys.path.insert(0, str(project))
    from setlist_bot.config import Settings
    from setlist_bot.core import AnalysisError, youtube_url
    from miniapp_full_analysis import analyze_full
    settings = Settings.load()
    if sys.argv[2] == "--check":
        emit("ready", max_minutes=settings.max_duration // 60, step=settings.step)
        return
    task = asyncio.current_task()
    asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, task.cancel)
    found = {}
    audio = None
    def snapshot():
        emit("progress", message=last_message, tracks=list(found.values()))
    def remember(track):
        from miniapp_audio_queue import track_key
        key = track_key(track)
        if key not in found:
            found[key] = track
            if audio:
                audio.add(track)
        elif track.get("timestamp") and not found[key].get("timestamp"):
            found[key]["timestamp"] = track["timestamp"]
    if len(sys.argv) > 3:
        from miniapp_audio_queue import AudioQueue
        audio = AudioQueue(settings, Path(sys.argv[3]), snapshot)
    last_message = "Ищем опубликованные треки…"
    async def discoveries(matches):
        from setlist_bot.core import timestamp
        for match in matches:
            remember({"artist": match.artist, "title": match.title,
                      "timestamp": timestamp(match.offset) if match.offset is not None else None})
        snapshot()

    async def progress(message):
        nonlocal last_message
        last_message = message
        # The existing analyser reports its latest discoveries after each new hit.
        # Accumulate them so the Mini App displays the entire growing list.
        for line in message.splitlines():
            match = re.match(r"^• (.+?) — (.+)$", line)
            if match:
                remember({"artist": match[1], "title": match[2], "timestamp": None})
        snapshot()
    try:
        if len(sys.argv) > 4 and sys.argv[4] == "--audio-only":
            data = json.loads((Path(sys.argv[3]) / "input.json").read_text())
            report, title = data["report"], data["title"]
            for track in data["tracks"]:
                remember(track)
        else:
            report = await analyze_full(youtube_url(sys.argv[2]), settings, progress, discoveries)
            title = report.splitlines()[0].removeprefix("🎧 ").strip()
        for track in report_tracks(report):
            remember(track)
        emit("report", report=report, title=title, tracks=list(found.values()))
        if audio:
            last_message = "Распознавание завершено. Ищем и скачиваем оставшиеся аудиофайлы…"
            snapshot()
            await audio.finish()
        emit("result", report=report, title=title, tracks=list(found.values()))
    except AnalysisError as exc:
        emit("error", message=str(exc))
    except asyncio.CancelledError:
        emit("cancelled")
    finally:
        if audio:
            await audio.close()


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    try:
        asyncio.run(run())
    except Exception:
        emit("error", message="Не удалось запустить анализ YouTube. Проверьте окружение анализатора.")
        sys.exit(1)
