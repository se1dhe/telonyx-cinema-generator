# Railway Deploy

## Target architecture

Create two Railway services from the same GitHub repository:

- `telonyx-cinema-api`
- `telonyx-cinema-worker`

Add one Redis plugin and one shared persistent volume mounted to both services.

## API service

Use Dockerfile build.

Start command:

```bash
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port $PORT
```

Expose public domain only for this service.

## Worker service

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

## Shared storage volume

Mount the same Railway volume to both API and Worker at:

```text
/data/storage
```

Set on both services:

```env
STORAGE_DIR=/data/storage
```

If API and Worker do not share the same volume, worker will fail with `input video not found`.

## Required env on both services

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

## Preflight

After deploy, open:

```text
/api/health
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

If `worker_heartbeat` is empty, the worker service is not connected to the same Redis or did not start.

## First production test

Use a short rough edit first.

Recommended settings:

```text
Duration: 15-20 seconds
Subtitles: off
Color: on
Transitions: on
Effects: medium
Centering: on
Whisper: disabled
```

Steps:

1. Open API service URL.
2. Upload a short rough movie edit.
3. Upload a music track.
4. Select 15-20 seconds.
5. Keep subtitles disabled for first test.
6. Start render.
7. Open `/api/jobs/{job_id}`.
8. Wait for `status=done`.
9. Download final MP4 from `output_url`.

## Cleanup command

Manual cleanup command:

```bash
python -m telonyx_cinema.maintenance.cleanup
```

It removes old job folders from `/data/storage` using `MAX_JOB_AGE_HOURS`.

## Notes

Whisper on Railway CPU can be slow. Keep `ENABLE_WHISPER=false` until the core render is stable.
