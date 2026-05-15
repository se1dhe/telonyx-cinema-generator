import os
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from redis import Redis
from rq import Queue

STORAGE_DIR = Path(os.getenv('STORAGE_DIR', '/data/storage'))
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
STORAGE_DIR.mkdir(parents=True, exist_ok=True)


async def create_job_handler(
    video: UploadFile = File(...),
    music: UploadFile | None = File(default=None),
    focus_prompt: str = Form(default=''),
    target_seconds: int = Form(default=30),
    enable_color: bool = Form(default=True),
    enable_subtitles: bool = Form(default=False),
):
    job_id = str(uuid.uuid4())
    job_dir = STORAGE_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    video_path = job_dir / 'video.mp4'
    video_path.write_bytes(await video.read())

    music_path = ''
    if music and music.filename:
        music_file = job_dir / 'music.mp3'
        music_file.write_bytes(await music.read())
        music_path = str(music_file)

    output_path = job_dir / 'final.mp4'
    payload = {
        'id': job_id,
        'status': 'queued',
        'progress': '0',
        'focus_prompt': focus_prompt,
        'target_seconds': str(target_seconds),
        'enable_color': str(enable_color).lower(),
        'enable_subtitles': str(enable_subtitles).lower(),
        'video_path': str(video_path),
        'music_path': music_path,
        'output_path': str(output_path),
    }

    redis = Redis.from_url(REDIS_URL)
    redis.hset(f'job:{job_id}', mapping=payload)
    Queue('render', connection=redis).enqueue('render_task.render_job', job_id)
    return {'job_id': job_id, 'status_url': f'/api/jobs/{job_id}'}


def get_job_handler(job_id: str):
    redis = Redis.from_url(REDIS_URL)
    data = redis.hgetall(f'job:{job_id}')
    if not data:
        raise HTTPException(status_code=404, detail='Job not found')
    result = {k.decode(): v.decode() for k, v in data.items()}
    if result.get('status') == 'done':
        result['output_url'] = f'/api/jobs/{job_id}/download'
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
