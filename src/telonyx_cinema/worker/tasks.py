import json
import os
import socket
import subprocess
import time
import traceback
from pathlib import Path

from redis import Redis

from telonyx_cinema.pipeline.beat_detector import detect_beats, save_beats
from telonyx_cinema.pipeline.beat_sync import align_segments_to_beats, build_relative_beat_grid
from telonyx_cinema.pipeline.concat_builder import render_segments
from telonyx_cinema.pipeline.input_normalizer import normalize_input_video
from telonyx_cinema.pipeline.scene_analyzer import build_segments, save_segments
from telonyx_cinema.pipeline.whisper_subtitles import build_subtitles

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def update_worker_heartbeat(redis: Redis, status: str, job_id: str | None = None) -> None:
    mapping = {
        'status': status,
        'host': socket.gethostname(),
        'updated_at': str(int(time.time())),
        'queue': 'render',
    }
    if job_id:
        mapping['job_id'] = job_id
    redis.hset('worker:heartbeat', mapping=mapping)


def run_cmd(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        command = ' '.join(cmd[:8])
        error_tail = (process.stderr or process.stdout or 'unknown ffmpeg error')[-3000:]
        raise RuntimeError(f'Command failed: {command}\n{error_tail}')


def fail_job(redis: Redis, key: str, error: Exception) -> None:
    error_text = str(error)[-4000:]
    traceback_text = traceback.format_exc()[-8000:]
    redis.hset(
        key,
        mapping={
            'status': 'failed',
            'progress': '100',
            'log': 'failed',
            'error': error_text,
            'traceback': traceback_text,
        },
    )


def set_progress(redis: Redis, key: str, progress: int, log: str) -> None:
    redis.hset(key, mapping={'status': 'processing', 'progress': str(progress), 'log': log})


def burn_subtitles(input_path: str, ass_path: str, output_path: str) -> None:
    safe_ass = ass_path.replace('\\', '/').replace(':', '\\:')
    run_cmd([
        'ffmpeg', '-y', '-i', input_path,
        '-vf', f'ass={safe_ass}',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        '-c:a', 'copy', output_path,
    ])


def render_job(job_id: str) -> None:
    redis = Redis.from_url(REDIS_URL)
    key = f'job:{job_id}'
    update_worker_heartbeat(redis, 'processing', job_id)

    try:
        data = redis.hgetall(key)
        if not data:
            raise RuntimeError('job not found')

        job = {k.decode(): v.decode() for k, v in data.items()}
        original_video_path = job['video_path']
        music_path = job.get('music_path') or ''
        output_path = job['output_path']
        target_seconds = int(job.get('target_seconds', '30'))
        platform = job.get('platform', 'shorts')
        color_enabled = job.get('color_enabled', 'true') == 'true'
        color_preset = job.get('color_preset', 'dark_cinema')
        subtitle_enabled = job.get('subtitle_enabled', 'false') == 'true'
        subtitle_language = job.get('subtitle_language', 'auto')
        subtitle_style = job.get('subtitle_style', 'cinematic')
        centering_enabled = job.get('centering_enabled', 'true') == 'true'
        transitions_enabled = job.get('transitions_enabled', 'true') == 'true'
        transition_style = job.get('transition_style', 'glitch')
        beat_sync = job.get('beat_sync', 'soft')
        music_start_seconds = float(job.get('music_start_seconds', '0') or 0)
        effects_enabled = job.get('effects_enabled', 'true') == 'true'
        effect_intensity = job.get('effect_intensity', 'medium')
        focus_prompt = job.get('focus_prompt') or 'TELONYX CINEMA'

        if not Path(original_video_path).exists():
            raise RuntimeError(f'input video not found: {original_video_path}')
        if music_path and not Path(music_path).exists():
            raise RuntimeError(f'music file not found: {music_path}')

        out_dir = Path(output_path).parent
        out_dir.mkdir(parents=True, exist_ok=True)

        render_summary = {
            'platform': platform,
            'target_seconds': target_seconds,
            'focus_prompt': focus_prompt,
            'music_enabled': bool(music_path),
            'music_start_seconds': music_start_seconds,
            'beat_sync': beat_sync,
            'color_enabled': color_enabled,
            'color_preset': color_preset,
            'subtitle_enabled': subtitle_enabled,
            'subtitle_language': subtitle_language,
            'subtitle_style': subtitle_style,
            'centering_enabled': centering_enabled,
            'transitions_enabled': transitions_enabled,
            'transition_style': transition_style,
            'effects_enabled': effects_enabled,
            'effect_intensity': effect_intensity,
            'input_normalization': 'h264_yuv420p',
        }
        redis.hset(key, mapping={'render_summary': json.dumps(render_summary, ensure_ascii=False)})

        set_progress(redis, key, 5, 'normalizing input video')
        video_path = normalize_input_video(original_video_path, str(out_dir))
        redis.hset(key, mapping={'normalized_video_path': video_path})

        set_progress(redis, key, 12, 'detecting beats')
        if music_path:
            beats = detect_beats(music_path)
            save_beats(str(out_dir / 'beats.txt'), beats)
            relative_beats = build_relative_beat_grid(beats, target_seconds, music_start_seconds)
            save_beats(str(out_dir / 'relative_beats.txt'), relative_beats)
        else:
            beats = []
            relative_beats = []

        set_progress(redis, key, 22, 'analyzing scenes')
        segments = build_segments(video_path, target_seconds)
        if not segments:
            raise RuntimeError('scene analyzer returned zero segments')
        segments = align_segments_to_beats(segments, relative_beats, target_seconds, beat_sync)
        if not segments:
            raise RuntimeError('beat sync returned zero segments')
        save_segments(str(out_dir / 'segments.json'), segments)

        set_progress(redis, key, 42, f'rendering {len(segments)} beat-synced segments')
        concat_list = render_segments(
            video_path=video_path,
            segments=segments,
            work_dir=str(out_dir / 'segments'),
            enable_color=color_enabled,
            color_preset=color_preset,
            enable_centering=centering_enabled,
            enable_effects=effects_enabled,
            effect_intensity=effect_intensity,
            transitions_enabled=transitions_enabled,
            transition_style=transition_style,
        )

        silent_path = str(out_dir / 'silent.mp4')
        run_cmd(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', concat_list, '-c', 'copy', silent_path])
        if not Path(silent_path).exists():
            raise RuntimeError('silent render output was not created')
        redis.hset(key, mapping={'progress': '78', 'log': 'video assembled'})

        mixed_path = str(out_dir / 'mixed.mp4')
        if music_path:
            run_cmd([
                'ffmpeg', '-y',
                '-ss', str(music_start_seconds),
                '-stream_loop', '-1', '-i', music_path,
                '-i', silent_path,
                '-t', str(target_seconds),
                '-map', '1:v:0', '-map', '0:a:0',
                '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', mixed_path,
            ])
            Path(silent_path).unlink(missing_ok=True)
        else:
            Path(silent_path).replace(mixed_path)

        if not Path(mixed_path).exists():
            raise RuntimeError('mixed render output was not created')

        if subtitle_enabled:
            set_progress(redis, key, 90, 'building subtitles')
            ass_path = str(out_dir / 'subtitles.ass')
            build_subtitles(mixed_path, ass_path, focus_prompt)
            burn_subtitles(mixed_path, ass_path, output_path)
            Path(mixed_path).unlink(missing_ok=True)
        else:
            Path(mixed_path).replace(output_path)

        if not Path(output_path).exists():
            raise RuntimeError('final render output was not created')

        redis.hset(key, mapping={'status': 'done', 'progress': '100', 'log': f'done, beats={len(beats)}, segments={len(segments)}'})
        update_worker_heartbeat(redis, 'idle', job_id)
    except Exception as error:
        fail_job(redis, key, error)
        update_worker_heartbeat(redis, 'failed', job_id)
        raise
