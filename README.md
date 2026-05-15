# TELONYX Cinema Generator

AI post-production web service for movie-based TikTok, Reels and YouTube Shorts edits.

The user uploads a rough movie edit, uploads a music track, selects render options and receives a polished vertical 1080x1920 MP4.

## Current status

Railway MVP is deploy-ready:

- FastAPI web service;
- Redis/RQ queue;
- separate worker service;
- shared storage volume support;
- web UI;
- diagnostics endpoint;
- worker heartbeat;
- upload validation;
- job timeout;
- robust failed-state handling;
- cleanup utility;
- Dockerfile;
- docker-compose local stack.

## Local run

```bash
chmod +x scripts/local_dev.sh
./scripts/local_dev.sh
```

Open:

```text
http://localhost:8080
http://localhost:8080/api/health
http://localhost:8080/api/diagnostics
```

## Railway services

### API service

Start command:

```bash
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port $PORT
```

### Worker service

Start command:

```bash
python -m telonyx_cinema.worker.main
```

## Required Railway resources

- API service from this repository.
- Worker service from this repository.
- Redis plugin.
- Persistent volume mounted to `/data/storage` for both API and worker.

## Required environment variables

```env
PYTHONPATH=/app/src
STORAGE_DIR=/data/storage
REDIS_URL=${{Redis.REDIS_URL}}
MAX_UPLOAD_MB=1200
RQ_JOB_TIMEOUT_SECONDS=1800
MAX_JOB_AGE_HOURS=48
ENABLE_YOLO=true
ENABLE_BEAT_DETECT=true
ENABLE_WHISPER=false
ENABLE_CLIP=false
MODEL_DEVICE=cpu
COMPUTE_TYPE=int8
YOLO_MODEL=yolov8n.pt
WHISPER_MODEL=base
```

## Diagnostics

After deploy, open:

```text
/api/diagnostics
```

Expected:

```json
{
  "redis_ok": true,
  "storage_ok": true,
  "worker_heartbeat": {
    "queue": "render"
  }
}
```

## Current pipeline

- Upload rough cut.
- Upload music.
- Validate upload size and extension.
- Create Redis/RQ job with timeout.
- Detect beats with librosa.
- Analyze scene changes with FFmpeg.
- Score motion with OpenCV.
- Detect focus with local YOLO/OpenCV.
- Smart vertical crop.
- Render selected segments.
- Apply color preset.
- Apply effect preset.
- Apply transition styling.
- Add music.
- Optionally burn ASS subtitles.
- Download final MP4.

## Cleanup

Manual cleanup:

```bash
python -m telonyx_cinema.maintenance.cleanup
```

## Project layout

Main code lives in:

```text
src/telonyx_cinema/
```

Do not add new production code to the repository root.
