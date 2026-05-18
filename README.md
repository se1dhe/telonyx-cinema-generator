# TELONYX Cinema Finalizer

Новый формат проекта: сервис больше не генерирует нарезку из фильма.

Теперь пайплайн такой:

1. пользователь загружает уже готовый момент из фильма;
2. указывает название фильма и год выхода;
3. сервис делает вертикальный MP4 `1080x1920`;
4. добавляет красивый выезжающий титр снизу слева в начале;
5. ближе к концу титр уезжает обратно;
6. при включённых субтитрах распознаёт речь через `faster-whisper`;
7. прожигает ASS-субтитры в итоговое видео;
8. после проверки результата пользователь нажимает **«Генерація»**;
9. сервис создаёт украинский Telegram-пост, metadata для TikTok/YouTube Shorts и 3–5 фирменных изображений;
10. после проверки preview пользователь нажимает **«Публікувати»**.

## Что отключено

Старые идеи про генерацию нарезок, Training Lab, YOLO, beat detector, Redis/RQ worker и сложный AI director больше не являются основным продуктом.

Новый продукт — быстрый финализатор готовых Shorts/TikTok moments + publishing pipeline.

## Локальный запуск

```bash
chmod +x scripts/local_dev.sh
./scripts/local_dev.sh
```

Открыть:

```text
http://localhost:8080
http://localhost:8080/api/health
```

## Railway

Один сервис из репозитория.

```env
PORT=8080
PYTHONPATH=/app/src
STORAGE_DIR=/data/storage
MAX_UPLOAD_MB=1200
ENABLE_WHISPER=true
WHISPER_MODEL=small
MODEL_DEVICE=cpu
COMPUTE_TYPE=int8

# Gemini для украинского контента
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash

# Telegram publishing
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHANNEL_ID=@TXC_UA

# Brand cards
BRAND_WATERMARK=TELONYX CINEMA
BRAND_STYLE=dark_neon_cinematic

# Будущие интеграции
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=

YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_DEFAULT_PRIVACY=public
```

Volume лучше монтировать в `/data/storage`.

> Важно: токен Telegram-бота нельзя хранить в репозитории. Если токен случайно попал в чат или публичное место — пересоздай его через BotFather.

## API

```text
GET  /
GET  /api/health
POST /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/download

POST /api/jobs/{job_id}/generate-package
GET  /api/publish-packages/{package_id}
GET  /api/publish-packages/{package_id}/images/{filename}
POST /api/publish-packages/{package_id}/regenerate-text
POST /api/publish-packages/{package_id}/publish
```

`POST /api/jobs` принимает multipart form:

```text
video              файл видео
movie_title        название фильма
movie_year         год выхода
language           auto / ru / en / uk
subtitles_enabled  true / false
```

Если `ENABLE_WHISPER=false`, сервис всё равно сделает вертикальный ролик и титр, но автосубтитры будут пропущены.

## Publishing MVP

После успешного рендера на сайте появляется кнопка **«Генерація»**.

Она запускает:

1. создание `PublishPackage`;
2. генерацию Telegram-поста на украинском языке;
3. генерацию title/description/hashtags для TikTok;
4. генерацию title/description/hashtags для YouTube Shorts;
5. создание 3–5 фирменных JPG-карточек TELONYX Cinema.

Если `GEMINI_API_KEY` не задан, сервис не падает. Он создаёт fallback-пакет, чтобы можно было тестировать UI и Telegram-публикацию.

## Telegram publishing

Для публикации в Telegram:

1. пересоздай токен через BotFather, если старый был где-то засвечен;
2. добавь бота админом в канал `@TXC_UA`;
3. положи токен в `TELEGRAM_BOT_TOKEN`;
4. оставь `TELEGRAM_CHANNEL_ID=@TXC_UA` или укажи числовой id канала.

Кнопка **«Публікувати в Telegram»** отправит 3–5 изображений как album и добавит текст поста.

## YouTube Shorts: что нужно получить

1. Создать проект в Google Cloud Console.
2. Включить YouTube Data API v3.
3. Создать OAuth Client ID типа Web application.
4. Добавить redirect URI будущего backend callback.
5. Получить `client_id`, `client_secret` и refresh token владельца YouTube-канала.
6. Добавить env:

```env
YOUTUBE_CLIENT_ID=
YOUTUBE_CLIENT_SECRET=
YOUTUBE_REDIRECT_URI=
YOUTUBE_REFRESH_TOKEN=
YOUTUBE_DEFAULT_PRIVACY=public
```

Shorts публикуется через `videos.insert` как обычное вертикальное видео. В title/description нужно оставлять `#Shorts`.

## TikTok: что нужно получить

1. Создать приложение в TikTok for Developers.
2. Подключить Login Kit и Content Posting API.
3. Добавить redirect URI backend callback.
4. Получить `client_key` и `client_secret`.
5. Пройти OAuth владельцем аккаунта.
6. Сохранить access/refresh token.
7. Добавить env:

```env
TIKTOK_CLIENT_KEY=
TIKTOK_CLIENT_SECRET=
TIKTOK_REDIRECT_URI=
TIKTOK_ACCESS_TOKEN=
TIKTOK_REFRESH_TOKEN=
```

Для production-публикации TikTok может требовать review/approval приложения.

## Документация

Подробный план publishing pipeline лежит в:

```text
docs/CINEMA_PUBLISHING_PIPELINE.md
```
