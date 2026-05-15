# Railway Deploy

## MVP architecture

For the first Railway launch use one service only:

- `telonyx-cinema-generator` web service
- Railway Redis plugin
- one persistent volume mounted to `/data/storage`

The Docker container starts both processes:

- FastAPI web API
- RQ Worker

This avoids cross-service shared-volume issues during the first MVP deploy.

## Service

Create one Railway service from this GitHub repository.

Use Dockerfile build.

The Dockerfile already starts:

```bash
/app/scripts/railway_start.sh
```

You can leave Railway Start Command empty. If Railway requires a start command, use:

```bash
/app/scripts/railway_start.sh
```

Expose public domain for this service.

## Redis

Add Railway Redis plugin and set:

```env
REDIS_URL=${{Redis.REDIS_URL}}
```

## Storage volume

Mount a Railway volume to this service at:

```text
/data/storage
```

Set:

```env
STORAGE_DIR=/data/storage
```

## Required env

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

If `worker_heartbeat` is empty, the background worker did not start inside the container.

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

1. Open Railway public URL.
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

## Later production architecture

After the MVP is stable, split into two Railway services:

- API service
- Worker service

But then file storage should be moved to S3/R2, not shared local volume.

## Notes

Whisper on Railway CPU can be slow. Keep `ENABLE_WHISPER=false` until the core render is stable.
