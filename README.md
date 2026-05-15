# TELONYX Cinema Generator

AI post-production web service for movie-based TikTok, Reels and YouTube Shorts edits.

The user uploads a rough movie edit, uploads a music track, selects render options and receives a polished vertical 1080x1920 MP4.

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
ENABLE_YOLO=true
ENABLE_BEAT_DETECT=true
ENABLE_WHISPER=false
ENABLE_CLIP=false
MODEL_DEVICE=cpu
COMPUTE_TYPE=int8
YOLO_MODEL=yolov8n.pt
WHISPER_MODEL=base
```

## Current pipeline

- Upload rough cut.
- Upload music.
- Create Redis/RQ job.
- Detect beats with librosa.
- Analyze scene changes with FFmpeg.
- Score motion with OpenCV.
- Detect focus with local YOLO/OpenCV.
- Smart vertical crop.
- Render selected segments.
- Apply color preset.
- Add music.
- Optionally burn ASS subtitles.
- Download final MP4.

## Project layout

Main code lives in:

```text
src/telonyx_cinema/
```

Do not add new production code to the repository root. Root-level Python files are legacy and should be removed or migrated.
