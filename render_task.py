import os
import subprocess
from pathlib import Path

from redis import Redis

from concat_builder import render_segments
from scene_analyzer import build_segments, save_segments

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def run_cmd(cmd):
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])


def render_job(job_id: str):
    redis = Redis.from_url(REDIS_URL)
    key = f'job:{job_id}'
    data = redis.hgetall(key)
    if not data:
        raise RuntimeError('job not found')

    decoded = {k.decode(): v.decode() for k, v in data.items()}
    video_path = decoded['video_path']
    music_path = decoded.get('music_path') or ''
    output_path = decoded['output_path']
    target_seconds = int(decoded.get('target_seconds', '30'))
    enable_color = decoded.get('enable_color', 'true').lower() == 'true'

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    redis.hset(key, mapping={'status': 'processing', 'progress': '10', 'log': 'analyzing scenes'})

    segments = build_segments(video_path, target_seconds)
    save_segments(str(output_dir / 'segments.json'), segments)
    redis.hset(key, mapping={'progress': '35', 'log': f'selected {len(segments)} segments'})

    concat_list = render_segments(video_path, segments, str(output_dir / 'segments'), enable_color)
    redis.hset(key, mapping={'progress': '70', 'log': 'segments rendered'})

    temp_path = str(Path(output_path).with_suffix('.silent.mp4'))
    run_cmd([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
        '-c', 'copy', temp_path,
    ])
    redis.hset(key, mapping={'progress': '82', 'log': 'video assembled'})

    if music_path:
        run_cmd([
            'ffmpeg', '-y', '-stream_loop', '-1', '-i', music_path, '-i', temp_path,
            '-t', str(target_seconds), '-map', '1:v:0', '-map', '0:a:0',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest',
            output_path,
        ])
        Path(temp_path).unlink(missing_ok=True)
    else:
        Path(temp_path).replace(output_path)

    redis.hset(key, mapping={'status': 'done', 'progress': '100', 'log': 'done'})
