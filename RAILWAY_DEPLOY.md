# Railway Deploy

## Services

Create two services from the same GitHub repository.

### API service

Use Dockerfile build.

Start command:

```bash
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port $PORT
```

Expose public domain for this service.

### Worker service

Use the same Dockerfile build.

Start command:

```bash
python -m telonyx_cinema.worker.main
```

Do not expose public domain for worker.

## Redis

Add Railway Redis plugin and set this variable on both API and Worker:

```env
REDIS_URL=${{Redis.REDIS_URL}}
```

## Storage volume

Mount a persistent volume to both API and Worker at:

```text
/data/storage
```

Set:

```env
STORAGE_DIR=/data/storage
```

## Recommended CPU config

```env
PYTHONPATH=/app/src
ENABLE_YOLO=true
ENABLE_BEAT_DETECT=true
ENABLE_WHISPER=false
ENABLE_CLIP=false
MODEL_DEVICE=cpu
COMPUTE_TYPE=int8
YOLO_MODEL=yolov8n.pt
WHISPER_MODEL=base
```

## First production test

1. Open API service URL.
2. Upload a short rough movie edit.
3. Upload a music track.
4. Select 20-30 seconds.
5. Keep Whisper subtitles disabled for first test.
6. Start render.
7. Wait for job status to become `done`.
8. Download final MP4.

## Notes

Whisper on Railway CPU can be slow. Keep `ENABLE_WHISPER=false` until the core render is stable.
