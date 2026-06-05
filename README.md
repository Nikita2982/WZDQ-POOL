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
4. Аудио временно скачивается в `/tmp/dj_ai_bot` или загружается во внешнее object storage.
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
- `storage_bucket`
- `storage_key`

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

## Разделение на dev и prod бота

Если хочешь спокойно тестировать локально и не конфликтовать с production polling, используй два разных Telegram-бота:

- `dev bot` для локального запуска на компьютере
- `prod bot` для VPS/сервера

Для этого в проекте уже подготовлены:

- [`.env.dev.example`](/Users/admin/Documents/DJ_AI_BOT/.env.dev.example)
- [`.env.prod.example`](/Users/admin/Documents/DJ_AI_BOT/.env.prod.example)
- [scripts/run_dev.sh](/Users/admin/Documents/DJ_AI_BOT/scripts/run_dev.sh)
- [scripts/run_prod.sh](/Users/admin/Documents/DJ_AI_BOT/scripts/run_prod.sh)

### Быстрый старт для dev

```bash
cp .env.dev.example .env.dev
```

Заполни в `.env.dev`:

- `TELEGRAM_BOT_TOKEN` dev-бота
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `SOURCE_CHAT`
- `CHANNEL_ID`
- `ADMIN_USER_IDS`
- `STORAGE_*`

Запуск:

```bash
bash scripts/run_dev.sh
```

### Быстрый старт для prod

```bash
cp .env.prod.example .env.prod
```

Заполни `.env.prod` production-значениями и запускай на сервере:

```bash
bash scripts/run_prod.sh
```

### Как это работает

- локальный `dev` использует `.env.dev`
- серверный `prod` использует `.env.prod`
- код один и тот же
- токены разные, поэтому `TelegramConflictError` между dev и prod не возникает

## Запуск на VPS 24/7

Рекомендуемая production-схема:

1. Код хранится на GitHub.
2. Один VPS постоянно запускает бота через `systemd`.
3. Локально ты только меняешь код, коммитишь и пушишь.
4. На сервере выполняется `git pull` и рестарт сервиса.

### Что подготовлено в репозитории

- systemd unit: [deploy/systemd/wzdq-bot.service](/Users/admin/Documents/DJ_AI_BOT/deploy/systemd/wzdq-bot.service)
- bootstrap-скрипт: [scripts/bootstrap_server.sh](/Users/admin/Documents/DJ_AI_BOT/scripts/bootstrap_server.sh)
- deploy-скрипт: [scripts/deploy_prod.sh](/Users/admin/Documents/DJ_AI_BOT/scripts/deploy_prod.sh)

### Первичная установка на сервере

```bash
sudo apt update
sudo apt install -y git python3 python3-venv ffmpeg
git clone https://github.com/Nikita2982/WZDQ-POOL.git /opt/WZDQ-POOL
cd /opt/WZDQ-POOL
bash scripts/bootstrap_server.sh /opt/WZDQ-POOL
cp .env.example .env
```

После этого нужно заполнить production `.env` реальными значениями:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `SOURCE_CHAT`
- `CHANNEL_ID`
- `ADMIN_USER_IDS`
- параметры `STORAGE_*`

### Подключение systemd

```bash
sudo cp deploy/systemd/wzdq-bot.service /etc/systemd/system/wzdq-bot.service
sudo nano /etc/systemd/system/wzdq-bot.service
```

Проверь в unit-файле:

- `User=ubuntu` или нужный серверный пользователь
- `WorkingDirectory=/opt/WZDQ-POOL`
- `ExecStart=/opt/WZDQ-POOL/venv/bin/python main.py`

Потом запусти:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wzdq-bot
sudo systemctl status wzdq-bot
```

### Обновление после push в GitHub

Когда ты внес локальные изменения и запушил их:

```bash
git add .
git commit -m "..."
git push
```

На сервере обновление делается так:

```bash
cd /opt/WZDQ-POOL
bash scripts/deploy_prod.sh /opt/WZDQ-POOL wzdq-bot main
```

## Автодеплой через GitHub Actions

В репозитории уже подготовлен workflow:

- [.github/workflows/deploy-prod.yml](/Users/admin/Documents/DJ_AI_BOT/.github/workflows/deploy-prod.yml)

Он делает деплой автоматически после каждого `push` в `main` и умеет запускаться вручную через `Run workflow`.

### Что нужно добавить в GitHub Secrets

В GitHub открой:

- `Repository -> Settings -> Secrets and variables -> Actions`

И создай secrets:

- `PROD_HOST`
  Твой IP сервера, например `45.150.10.25`
- `PROD_USER`
  Обычно `root`
- `PROD_PORT`
  Обычно `22`
- `PROD_SSH_KEY`
  Приватный SSH-ключ, которым GitHub сможет зайти на сервер

### Как подготовить SSH-ключ для автодеплоя

На своем Mac создай отдельный ключ именно для GitHub Actions:

```bash
ssh-keygen -t ed25519 -C "github-deploy" -f ~/.ssh/github_wzdq_deploy
```

Это создаст:

- приватный ключ: `~/.ssh/github_wzdq_deploy`
- публичный ключ: `~/.ssh/github_wzdq_deploy.pub`

Потом:

1. Добавь публичный ключ на сервер в `authorized_keys`

```bash
cat ~/.ssh/github_wzdq_deploy.pub
```

Скопируй вывод и на сервере добавь его в:

```bash
/root/.ssh/authorized_keys
```

2. Содержимое приватного ключа:

```bash
cat ~/.ssh/github_wzdq_deploy
```

целиком вставь в GitHub secret `PROD_SSH_KEY`.

### Как будет работать дальше

После настройки secrets цикл станет таким:

1. Локально тестируешь на `dev`-боте.
2. Делаешь:

```bash
git add .
git commit -m "..."
git push
```

3. GitHub Actions сам:
   - зайдет на сервер
   - сделает `git pull`
   - установит зависимости
   - перезапустит `wzdq-bot`

То есть отдельный ручной `git pull` на сервере больше не понадобится.

### Полезные команды на сервере

```bash
sudo systemctl restart wzdq-bot
sudo systemctl stop wzdq-bot
sudo systemctl status wzdq-bot
journalctl -u wzdq-bot -f
```

### Важное правило для production

Если используешь один и тот же `BOT_TOKEN` на сервере, не поднимай второй polling этого же бота локально на компьютере параллельно. Иначе Telegram вернет `TelegramConflictError`.

## Пример `.env`

См. [`.env.example`](/Users/admin/Documents/DJ_AI_BOT/.env.example).

## Внешнее хранилище треков

Чтобы аудио после сканирования не копилось на локальном ПК, можно включить S3-compatible storage:

- `STORAGE_ENABLED=true`
- `STORAGE_ENDPOINT_URL=...`
- `STORAGE_ACCESS_KEY_ID=...`
- `STORAGE_SECRET_ACCESS_KEY=...`
- `STORAGE_BUCKET=...`
- `STORAGE_REGION=...`
- `STORAGE_PREFIX=tracks`

После этого сканер:

1. скачивает трек временно;
2. анализирует BPM/key;
3. загружает файл в object storage;
4. сохраняет `storage_bucket` и `storage_key` в БД;
5. удаляет локальную копию.

При генерации плейлиста бот сначала пытается взять файл из storage, и только для старых треков без storage fallback'ится на Telegram.

Чтобы догрузить в облако уже просканированные треки и удалить локальные копии, запусти:

```bash
venv/bin/python scripts/backfill_storage.py
```

Можно ограничить пробный прогон, например первыми 20 треками:

```bash
venv/bin/python scripts/backfill_storage.py 20
```

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
