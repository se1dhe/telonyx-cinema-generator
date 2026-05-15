import os
import subprocess
from pathlib import Path

from redis import Redis

from beat_detector import detect_beats, save_beats
from concat_builder import render_segments
from scene_analyzer import build_segments, save_segments
from whisper_subtitles import build_subtitles

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def run_cmd(cmd):
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])


def burn_subtitles(input_path: str, ass_path: str, output_path: str) -> None:
    safe_ass = ass_path.replace('\\', '/').replace(':', '\\:')
    run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', f'ass={safe_ass}',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        '-c:a', 'copy', output_path,
    ])


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
    enable_subtitles = decoded.get('enable_subtitles', 'false').lower() == 'true'
    focus_prompt = decoded.get('focus_prompt') or 'TELONYX CINEMA'

    output_dir = Path(output_path).parent
    output_dir.mkdir(parents=True, exist_ok=True)
    redis.hset(key, mapping={'status': 'processing', 'progress': '8', 'log': 'detecting beats'})

    if music_path:
        beats = detect_beats(music_path)
        save_beats(str(output_dir / 'beats.txt'), beats)
    else:
        beats = []
    redis.hset(key, mapping={'progress': '12', 'log': f'detected {len(beats)} beats'})

    redis.hset(key, mapping={'progress': '18', 'log': 'analyzing scenes'})
    segments = build_segments(video_path, target_seconds)
    save_segments(str(output_dir / 'segments.json'), segments)
    redis.hset(key, mapping={'progress': '35', 'log': f'selected {len(segments)} segments'})

    concat_list = render_segments(video_path, segments, str(output_dir / 'segments'), enable_color)
    redis.hset(key, mapping={'progress': '70', 'log': 'segments rendered'})

    silent_path = str(Path(output_path).with_suffix('.silent.mp4'))
    run_cmd([
        'ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list,
        '-c', 'copy', silent_path,
    ])
    redis.hset(key, mapping={'progress': '82', 'log': 'video assembled'})

    mixed_path = str(Path(output_path).with_suffix('.mixed.mp4'))
    if music_path:
        run_cmd([
            'ffmpeg', '-y', '-stream_loop', '-1', '-i', music_path, '-i', silent_path,
            '-t', str(target_seconds), '-map', '1:v:0', '-map', '0:a:0',
            '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest',
            mixed_path,
        ])
        Path(silent_path).unlink(missing_ok=True)
    else:
        Path(silent_path).replace(mixed_path)

    if enable_subtitles:
        redis.hset(key, mapping={'progress': '90', 'log': 'building subtitles'})
        ass_path = str(output_dir / 'subtitles.ass')
        build_subtitles(mixed_path, ass_path, focus_prompt)
        burn_subtitles(mixed_path, ass_path, output_path)
        Path(mixed_path).unlink(missing_ok=True)
    else:
        Path(mixed_path).replace(output_path)

    redis.hset(key, mapping={'status': 'done', 'progress': '100', 'log': 'done'})
