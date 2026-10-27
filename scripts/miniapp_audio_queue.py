"""Download discoveries sequentially while set recognition continues independently."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
import shutil


def track_key(track):
    return tuple(' '.join(track[field].casefold().split()) for field in ('artist', 'title'))


def track_id(track):
    return hashlib.sha256(json.dumps(track_key(track), ensure_ascii=False).encode()).hexdigest()[:24]


class AudioQueue:
    def __init__(self, settings, root, changed):
        self.settings, self.root, self.changed = settings, Path(root), changed
        self.queue = asyncio.Queue()
        self.known = set()
        self.bytes = 0
        self.consumer = asyncio.create_task(self.consume())

    def add(self, track):
        key = track_key(track)
        if key in self.known:
            return
        self.known.add(key)
        cached = track.get('audio', {})
        path = self.root / (track_id(track) + '.mp3')
        if cached.get('status') == 'ready' and path.is_file():
            self.bytes += path.stat().st_size
            return
        track['audio'] = {'id': track_id(track), 'status': 'queued'}
        self.queue.put_nowait(track)

    async def consume(self):
        from setlist_bot.audio_search import find_audio
        from setlist_bot.audio_quality import quality_caption
        from setlist_bot.core import Match
        while True:
            track = await self.queue.get()
            audio = track['audio']
            work = self.root / (audio['id'] + '.work')
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(self.root).free < 1024**3 or self.bytes >= 1024**3:
                    audio.update(status='failed', message='Недостаточно места для аудиофайлов.')
                    self.changed()
                    continue
                work.mkdir(exist_ok=True)
                audio['status'] = 'searching'
                self.changed()
                async def downloading(message):
                    audio['status'] = 'downloading'
                    self.changed()
                result = await asyncio.wait_for(find_audio(
                    Match(track['artist'], track['title']), self.settings, work, downloading), timeout=90)
                if result is None:
                    audio.update(status='missing', message='Подходящий аудиофайл не найден.')
                else:
                    size = result.path.stat().st_size
                    if not 0 < size <= 45 * 1024**2 or self.bytes + size > 1024**3:
                        raise ValueError('Audio size limit')
                    target = self.root / (audio['id'] + '.mp3')
                    result.path.replace(target)
                    self.bytes += size
                    filename = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '', f"{track['artist']} — {track['title']}")
                    filename = filename.encode()[:180].decode(errors='ignore').strip() or 'track'
                    audio.update(status='ready', filename=filename+'.mp3', size_bytes=size,
                                 quality=quality_caption(result))
            except asyncio.CancelledError:
                audio.update(status='stopped', message='Поиск аудио остановлен.')
                raise
            except Exception:
                audio.update(status='failed', message='Источник не ответил. Аудиофайл не получен.')
            finally:
                shutil.rmtree(work, ignore_errors=True)
                self.queue.task_done()
                self.changed()

    async def finish(self):
        # Propagate an unexpected consumer failure instead of waiting forever.
        join = asyncio.create_task(self.queue.join())
        try:
            done, _ = await asyncio.wait([join, self.consumer], return_when=asyncio.FIRST_COMPLETED)
            if self.consumer in done:
                await self.consumer
            await join
        finally:
            join.cancel()
            await self.close()

    async def close(self):
        self.consumer.cancel()
        await asyncio.gather(self.consumer, return_exceptions=True)
