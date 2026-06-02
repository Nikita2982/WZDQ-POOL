# DJ AI Bot MVP

Telegram-бот для DJ, который сканирует аудио из Telegram-источника, анализирует треки и собирает готовый playlist order под жанр, длительность и настроение.

## Архитектура

- `aiogram 3` отвечает за пользовательский и админский Telegram-интерфейс.
- `Telethon` используется для чтения истории канала/супергруппы и скачивания аудио. Для MVP это практичнее, чем пытаться читать старую историю только через Bot API.
- `FastAPI` дает healthcheck и минимальные admin endpoints.
- `PostgreSQL` хранит метаданные треков, результаты анализа и состояние сканов.
- `Redis` зарезервирован под кэш/очереди. В MVP используется как инфраструктурная точка расширения.
- `librosa + mutagen + ffmpeg` анализируют BPM, key, duration и rough energy.

Поток данных:

1. Админ запускает `/scan_channel`.
2. `Telethon` проходит по сообщениям с аудио в источнике.
3. Система определяет жанр по `#hashtags`, topic id или fallback mapping.
4. Аудио временно скачивается в `/tmp/dj_ai_bot`.
5. Анализатор считает BPM, key, Camelot, energy.
6. Результат сохраняется в `tracks`.
7. Пользователь в боте выбирает жанр, длительность, настроение.
8. Генератор строит harmonic-friendly playlist.
9. Бот отправляет порядок треков и ссылки на сообщения.

## Ограничения Telegram API

- Bot API не дает удобно читать произвольную историю закрытого/чужого канала так, как это делает пользовательский клиент.
- "Папки" или боковое меню Telegram-канала не являются доступной сущностью API. Их нельзя надежно использовать как источник жанровой структуры.
- Forum Topics доступны в супергруппах, а не в обычных каналах. Для канала это не универсальное решение.
- Для приватных источников нужен доступ аккаунта, который реально состоит в канале.
- Генерация ZIP с музыкой технически возможна, но юридически и по лимитам Telegram это нужно включать осознанно.

## Лучший способ организовать жанры

Для MVP рекомендован такой приоритет:

1. `#genre_slug` в подписи к аудио, например `#afro_house`.
2. Отдельный канал/супергруппа на жанр, если контент уже хорошо разделен.
3. Topic-based структура для forum supergroup.
4. Ручная правка жанра через БД/API для спорных треков.

Почему хэштеги лучше всего для MVP:

- не зависят от недоступных API-сущностей;
- легко поддерживаются вручную;
- читаются и ботом, и userbot-клиентом;
- их можно ретроактивно добавить к старым постам.

## База данных

Основная таблица `tracks`:

- `id`
- `telegram_message_id`
- `telegram_file_id`
- `telegram_channel_id`
- `genre`
- `artist`
- `title`
- `duration_sec`
- `bpm`
- `musical_key`
- `camelot_key`
- `energy_level`
- `file_hash`
- `analyzed_at`
- `created_at`
- `updated_at`

Дополнительно в MVP:

- `message_link`
- `source_topic_id`
- `is_suitable`
- `suitability_score`
- `analysis_notes`

## Модули проекта

- [main.py](/Users/admin/Documents/DJ_AI_BOT/main.py)
- [config/settings.py](/Users/admin/Documents/DJ_AI_BOT/config/settings.py)
- [database/models.py](/Users/admin/Documents/DJ_AI_BOT/database/models.py)
- [database/crud.py](/Users/admin/Documents/DJ_AI_BOT/database/crud.py)
- [analysis/audio_analyzer.py](/Users/admin/Documents/DJ_AI_BOT/analysis/audio_analyzer.py)
- [analysis/camelot.py](/Users/admin/Documents/DJ_AI_BOT/analysis/camelot.py)
- [scanner/scan_tracks.py](/Users/admin/Documents/DJ_AI_BOT/scanner/scan_tracks.py)
- [bot/services/playlist_generator.py](/Users/admin/Documents/DJ_AI_BOT/bot/services/playlist_generator.py)
- [bot/services/harmonic_mixing.py](/Users/admin/Documents/DJ_AI_BOT/bot/services/harmonic_mixing.py)
- [bot/handlers/user.py](/Users/admin/Documents/DJ_AI_BOT/bot/handlers/user.py)
- [bot/handlers/admin.py](/Users/admin/Documents/DJ_AI_BOT/bot/handlers/admin.py)
- [api/app.py](/Users/admin/Documents/DJ_AI_BOT/api/app.py)

## Алгоритм генерации DJ-плейлиста

Функция `generate_dj_playlist(tracks, target_duration_minutes, mood)`:

1. фильтрует треки по жанру и выбрасывает записи без `bpm` или `camelot_key`;
2. задает целевой диапазон по настроению;
3. выбирает стартовый трек с подходящими `bpm` и `energy`;
4. жадно добирает следующий трек по score:
   - Camelot compatibility;
   - небольшой шаг по BPM;
   - плавный рост или стабильность energy;
   - бонус за близость к target mood;
5. останавливается около целевой длительности;
6. возвращает итоговый порядок и объяснение.

Поддерживаемые harmonic transitions:

- `8A -> 9A`
- `8A -> 7A`
- `8A -> 8B`
- exact match также разрешен

## Внешние API, которые можно подключить позже

Точки расширения уже заложены в `AudioAnalyzer`:

- Spotify metadata search
- MusicBrainz lookup
- AcousticBrainz / аналоги
- импорт вручную подготовленных BPM/key из Rekordbox или Mixed In Key

## Быстрый старт

1. Скопируйте `.env.example` в `.env` и заполните переменные.
2. Убедитесь, что Telegram account для `Telethon` состоит в исходном канале.
3. Запустите:

```bash
docker compose up --build
```

4. API будет доступен на `http://localhost:8080/docs`.
5. Бот запускается polling-процессом внутри контейнера `app`.

## Локальный запуск без Docker

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python main.py
```

Также нужен локальный `ffmpeg`.

## Пример `.env`

См. [`.env.example`](/Users/admin/Documents/DJ_AI_BOT/.env.example).

## Docker

- [Dockerfile](/Users/admin/Documents/DJ_AI_BOT/Dockerfile)
- [docker-compose.yml](/Users/admin/Documents/DJ_AI_BOT/docker-compose.yml)

## Что умеет MVP

- `/start`
- выбор жанра / длительности / настроения
- генерация плейлиста из БД
- `/scan_channel`
- `/stats`
- `/mark_unsuitable <track_id>`
- `/fix_track <track_id> <bpm> <camelot_key>`
- API: `/health`, `/tracks`, `/admin/scan`

## Следующие улучшения

- вынести сканирование и анализ в отдельный worker на `arq` или `celery`;
- добавить real admin panel с фильтрами и ручной разметкой;
- прикрутить S3-compatible storage для временных файлов и ZIP export;
- сохранять waveform/preview и confidence score анализа;
- импортировать подготовленные теги из Rekordbox XML;
- добавлять user taste profile и избегать повторов между сессиями;
- делать auto-crate building по времени суток, venue size и warm-up curve.
