"""Full Mini App analysis using the standalone bot's tested analysis primitives."""
import json
import math
from pathlib import Path
from tempfile import TemporaryDirectory


async def analyze_full(url, settings, progress, discoveries):
    from setlist_bot import analyzer as engine
    from setlist_bot.core import AnalysisError, render
    from setlist_bot.tracklist_search import SearchResult

    common = [str(engine.sys.executable), '-m', 'yt_dlp', '--no-playlist', '--quiet', '--no-warnings',
              '--socket-timeout', '20', '--retries', '3', '--extractor-retries', '2', '--http-chunk-size', '1M']
    if settings.youtube_proxy:
        common += ['--proxy', settings.youtube_proxy]
    if settings.cookies:
        common += ['--cookies', settings.cookies]
    with TemporaryDirectory(prefix='miniapp-youtube-') as directory:
        root = Path(directory)
        await progress('Ищем треклист в описании, главах и комментариях…')
        args = ['--skip-download', '--dump-single-json']
        if settings.published_search:
            args += ['--write-comments', '--extractor-args',
                     f'youtube:comment_sort=top;max_comments={settings.comments_limit},all,all,4']
        try:
            metadata = json.loads(await engine.command(*common, *args, url, timeout=35))
        except (AnalysisError, TimeoutError):
            metadata = json.loads(await engine.command(*common, '--skip-download', '--dump-single-json', url, timeout=30))
        title = str(metadata.get('title') or 'DJ-сет')
        published = SearchResult()
        if settings.published_search:
            published = await engine.find_published(metadata, url, progress)
            await discoveries(published.matches)
        note = 'Опубликованные треки дополнены распознаванием аудио. Список может быть неполным.'

        def partial(reason):
            return render(title, url, published.matches, 0, 0, 0, warning=reason,
                          note='Список из публикаций. Распознавание аудио не завершено.')

        duration = metadata.get('duration')
        try:
            if metadata.get('is_live') or not duration or duration <= 0:
                raise AnalysisError('Поддерживаются завершённые видео с известной длительностью.')
            if duration > settings.max_duration:
                raise AnalysisError(f'Видео слишком длинное. Максимум: {settings.max_duration // 60} мин.')
            total = math.ceil(duration / settings.step)
            if total > settings.max_requests:
                raise AnalysisError(f'Нужно {total} запросов распознавания; лимит — {settings.max_requests}.')
            await progress(f'В публикациях найдено: {len(published.matches)}. Продолжаем анализ всего аудио.\n'
                           f'Скачиваем аудио ({math.ceil(duration / 60)} мин.). Затем проверим {total} фрагментов.')
            info = root / 'info.json'
            info.write_text(json.dumps(metadata))
            await engine.download_audio([*common, '--load-info-json', str(info), '--max-filesize', '500M',
                                         '--continue', '-f', 'bestaudio/best', '-o', str(root / 'audio.%(ext)s')], progress)
            files = [p for p in root.glob('audio.*') if p.suffix not in {'.part', '.ytdl'}]
            if len(files) != 1:
                raise AnalysisError('Не удалось скачать аудио (лимит размера — 500 МБ).')
        except (AnalysisError, TimeoutError) as exc:
            if published.matches:
                return partial(str(exc) or 'Не удалось получить аудио вовремя.')
            raise
        await progress('Аудио готово. Начинаем распознавать сет от начала до конца…')
        matches, unknown, checked, missed, failed, warning = await engine.scan_audio(files[0], duration, settings, progress)
        note += f' Проверено фрагментов: {checked}/{total}.'
        return render(title, url, published.matches + matches, checked, missed, failed, warning=warning, note=note)
