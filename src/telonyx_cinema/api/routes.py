import os
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue

from telonyx_cinema.api.upload_validation import ensure_saved_size, validate_audio_upload, validate_video_upload
from telonyx_cinema.config.render_options import RenderOptions, options_to_redis_mapping

STORAGE_DIR = Path(os.getenv('STORAGE_DIR', '/data/storage'))
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
RQ_JOB_TIMEOUT_SECONDS = int(os.getenv('RQ_JOB_TIMEOUT_SECONDS', '1800'))
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


async def create_job_handler(
    video: UploadFile = File(...),
    music: UploadFile | None = File(default=None),
    focus_prompt: str = Form(default=''),
    target_seconds: int = Form(default=30),
    platform: str = Form(default='shorts'),
    subtitle_enabled: bool = Form(default=False),
    subtitle_language: str = Form(default='auto'),
    subtitle_style: str = Form(default='cinematic'),
    color_enabled: bool = Form(default=True),
    color_preset: str = Form(default='dark_cinema'),
    transitions_enabled: bool = Form(default=True),
    transition_style: str = Form(default='glitch'),
    centering_enabled: bool = Form(default=True),
    effects_enabled: bool = Form(default=True),
    effect_intensity: str = Form(default='medium'),
):
    validate_video_upload(video)
    if music and music.filename:
        validate_audio_upload(music)

    if target_seconds < 5 or target_seconds > 180:
        raise HTTPException(status_code=400, detail='target_seconds must be between 5 and 180')

    job_id = str(uuid.uuid4())
    job_dir = STORAGE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = job_dir / 'rough_cut.mp4'
    video_path.write_bytes(await video.read())
    ensure_saved_size(video_path, 'Video')

    music_path = ''
    if music and music.filename:
        music_suffix = Path(music.filename).suffix.lower()
        music_file = job_dir / f'music{music_suffix}'
        music_file.write_bytes(await music.read())
        ensure_saved_size(music_file, 'Music')
        music_path = str(music_file)

    options = RenderOptions(
        platform=platform,
        target_seconds=target_seconds,
        focus_prompt=focus_prompt,
        subtitle_enabled=subtitle_enabled,
        subtitle_language=subtitle_language,
        subtitle_style=subtitle_style,
        color_enabled=color_enabled,
        color_preset=color_preset,
        transitions_enabled=transitions_enabled,
        transition_style=transition_style,
        centering_enabled=centering_enabled,
        effects_enabled=effects_enabled,
        effect_intensity=effect_intensity,
    )

    output_path = job_dir / 'final.mp4'
    payload = {
        'id': job_id,
        'status': 'queued',
        'progress': '0',
        'video_path': str(video_path),
        'music_path': music_path,
        'output_path': str(output_path),
        **options_to_redis_mapping(options),
    }

    redis = Redis.from_url(REDIS_URL)
    redis.hset(f'job:{job_id}', mapping=payload)
    Queue('render', connection=redis).enqueue(
        'telonyx_cinema.worker.tasks.render_job',
        job_id,
        job_timeout=RQ_JOB_TIMEOUT_SECONDS,
        result_ttl=86400,
        failure_ttl=86400,
    )
    return {'job_id': job_id, 'status_url': f'/api/jobs/{job_id}'}


def get_job_handler(job_id: str):
    redis = Redis.from_url(REDIS_URL)
    data = redis.hgetall(f'job:{job_id}')
    if not data:
        raise HTTPException(status_code=404, detail='Job not found')

    result = {k.decode(): v.decode() for k, v in data.items()}
    output_path = result.get('output_path')
    output_exists = bool(output_path and Path(output_path).exists())
    result['output_exists'] = str(output_exists).lower()

    if result.get('status') == 'done' and output_exists:
        result['output_url'] = f'/api/jobs/{job_id}/download'
    elif result.get('status') == 'done' and not output_exists:
        result['status'] = 'failed'
        result['error'] = 'Render marked as done but final file does not exist'

    return result


def download_handler(job_id: str):
    redis = Redis.from_url(REDIS_URL)
    output = redis.hget(f'job:{job_id}', 'output_path')
    if not output:
        raise HTTPException(status_code=404, detail='Output not found')
    path = Path(output.decode())
    if not path.exists():
        raise HTTPException(status_code=404, detail='File not ready')
    return FileResponse(path, media_type='video/mp4', filename=f'telonyx-{job_id}.mp4')
