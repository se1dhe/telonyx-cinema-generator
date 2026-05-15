import os
import subprocess
from pathlib import Path

from redis import Redis

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def run_cmd(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])


def render_job(job_id: str) -> None:
    redis = Redis.from_url(REDIS_URL)
    key = f'job:{job_id}'
    data = redis.hgetall(key)
    if not data:
        raise RuntimeError('job not found')

    job = {k.decode(): v.decode() for k, v in data.items()}
    video_path = job['video_path']
    music_path = job.get('music_path') or ''
    output_path = job['output_path']
    target_seconds = int(job.get('target_seconds', '30'))
    color_enabled = job.get('color_enabled', 'true') == 'true'
    color_preset = job.get('color_preset', 'dark_cinema')

    out_dir = Path(output_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    redis.hset(key, mapping={'status': 'processing', 'progress': '10', 'log': 'render started'})

    color = {
        'dark_cinema': 'eq=contrast=1.14:saturation=1.05:brightness=-0.025,unsharp=5:5:0.75:3:3:0.35',
        'cyberpunk_neon': 'eq=contrast=1.18:saturation=1.22:brightness=-0.015,unsharp=5:5:0.8:3:3:0.4',
        'vader_red': 'eq=contrast=1.2:saturation=1.12:brightness=-0.035,unsharp=5:5:0.85:3:3:0.45',
        'drive_night': 'eq=contrast=1.1:saturation=0.95:brightness=-0.02,unsharp=5:5:0.65:3:3:0.3',
        'neutral': 'eq=contrast=1.04:saturation=1.0:brightness=0.0',
    }.get(color_preset, 'eq=contrast=1.14:saturation=1.05:brightness=-0.025')

    vf = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
    if color_enabled:
        vf = vf + ',' + color

    silent_path = str(out_dir / 'silent.mp4')
    run_cmd(['ffmpeg', '-y', '-i', video_path, '-t', str(target_seconds), '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', silent_path])
    redis.hset(key, mapping={'progress': '70', 'log': 'video rendered'})

    if music_path:
        run_cmd(['ffmpeg', '-y', '-stream_loop', '-1', '-i', music_path, '-i', silent_path, '-t', str(target_seconds), '-map', '1:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', output_path])
        Path(silent_path).unlink(missing_ok=True)
    else:
        Path(silent_path).replace(output_path)

    redis.hset(key, mapping={'status': 'done', 'progress': '100', 'log': 'done'})
