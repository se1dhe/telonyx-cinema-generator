# Testing TELONYX Cinema Generator

## Goal

This checklist verifies that the service is ready for Railway production testing.

## 1. API health

Open:

```text
/api/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "api"
}
```

## 2. Web UI

Open the root URL:

```text
/
```

Expected:

- dark TELONYX interface is visible;
- upload field for rough video exists;
- upload field for music exists;
- controls for color, transitions, subtitles, effects and centering are visible.

## 3. Redis connection

Create a job from UI.

Expected:

```json
{
  "job_id": "...",
  "status_url": "/api/jobs/..."
}
```

If this fails, check:

```env
REDIS_URL
```

## 4. Worker connection

After job creation, open:

```text
/api/jobs/{job_id}
```

Expected progression:

```text
queued -> processing -> done
```

If the job stays in `queued`, the worker is not running or cannot connect to Redis.

## 5. Volume check

Both API and Worker must share the same mounted volume:

```text
/data/storage
```

If API uploads files but worker says `input video not found`, the services do not share the same volume.

## 6. First safe render settings

Use a short video file first.

Recommended first test:

```text
Duration: 15-20 seconds
Subtitles: off
Color: on
Transitions: on
Effects: medium
Centering: on
Whisper: disabled
```

Recommended env:

```env
ENABLE_YOLO=true
ENABLE_BEAT_DETECT=true
ENABLE_WHISPER=false
ENABLE_CLIP=false
MODEL_DEVICE=cpu
COMPUTE_TYPE=int8
```

## 7. Download final file

When status is `done`, response should include:

```json
{
  "output_exists": "true",
  "output_url": "/api/jobs/{job_id}/download"
}
```

Open the `output_url` and download final MP4.

## 8. Failed job debugging

If status is `failed`, inspect:

```json
{
  "error": "...",
  "traceback": "..."
}
```

Common issues:

| Symptom | Cause | Fix |
|---|---|---|
| job stays queued | worker is not running | check Worker service start command |
| input video not found | API and Worker do not share volume | mount same volume to both services |
| ffmpeg command failed | filter or codec error | inspect `error` field |
| output_exists=false | final file was not created | inspect worker logs |
| Whisper is too slow | CPU worker is weak | keep `ENABLE_WHISPER=false` |

## 9. Railway service commands

API:

```bash
uvicorn telonyx_cinema.api.main:app --host 0.0.0.0 --port $PORT
```

Worker:

```bash
python -m telonyx_cinema.worker.main
```
