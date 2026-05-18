# TELONYX Cinema Finalizer

Новый формат проекта: сервис больше не генерирует нарезку из фильма.

Теперь пайплайн такой:

1. пользователь загружает уже готовый момент из фильма;
2. указывает название фильма и год выхода;
3. сервис делает вертикальный MP4 `1080x1920`;
4. добавляет красивый выезжающий титр снизу слева в начале;
5. ближе к концу титр уезжает обратно;
6. при включённых субтитрах распознаёт речь через `faster-whisper`;
7. прожигает ASS-субтитры в итоговое видео.

## Что отключено

Старые идеи про генерацию нарезок, Training Lab, YOLO, beat detector, Redis/RQ worker и сложный AI director больше не являются основным продуктом.

Новый продукт — быстрый финализатор готовых Shorts/TikTok moments.

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
```

Volume лучше монтировать в `/data/storage`.

## API

```text
GET  /
GET  /api/health
POST /api/jobs
GET  /api/jobs/{job_id}
GET  /api/jobs/{job_id}/download
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
