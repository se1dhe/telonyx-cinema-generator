import json
import os
import socket
import subprocess
import time
import traceback
from pathlib import Path

from redis import Redis

from telonyx_cinema.pipeline.concat_builder import render_segments_with_xfade
from telonyx_cinema.pipeline.debug_timeline import build_debug_timeline, save_debug_timeline, save_debug_timeline_html
from telonyx_cinema.pipeline.edit_planner import build_premium_edit_plan, save_edit_plan
from telonyx_cinema.pipeline.input_normalizer import normalize_input_video
from telonyx_cinema.pipeline.music_analyzer import analyze_music, save_music_analysis
from telonyx_cinema.pipeline.scene_analyzer import build_segments, save_segments
from telonyx_cinema.pipeline.video_moment_selector import save_video_moments, select_video_moments
from telonyx_cinema.pipeline.whisper_subtitles import build_subtitles

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def update_worker_heartbeat(redis: Redis, status: str, job_id: str | None = None) -> None:
    mapping = {'status': status, 'host': socket.gethostname(), 'updated_at': str(int(time.time())), 'queue': 'render'}
    if job_id:
        mapping['job_id'] = job_id
    redis.hset('worker:heartbeat', mapping=mapping)


def run_cmd(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        command = ' '.join(cmd[:8])
        error_tail = (process.stderr or process.stdout or 'unknown ffmpeg error')[-4000:]
        raise RuntimeError(f'Command failed: {command}\n{error_tail}')


def fail_job(redis: Redis, key: str, error: Exception) -> None:
    redis.hset(key, mapping={'status': 'failed', 'progress': '100', 'log': 'failed', 'error': str(error)[-4000:], 'traceback': traceback.format_exc()[-8000:]})


def set_progress(redis: Redis, key: str, progress: int, log: str) -> None:
    redis.hset(key, mapping={'status': 'processing', 'progress': str(progress), 'log': log})


def burn_subtitles(input_path: str, ass_path: str, output_path: str) -> None:
    safe_ass = ass_path.replace('\\', '/').replace(':', '\\:')
    run_cmd(['ffmpeg', '-y', '-i', input_path, '-vf', f'ass={safe_ass}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-c:a', 'copy', output_path])


def build_segments_for_job(video_path: str, music_path: str, out_dir: Path, target_seconds: int, music_start_seconds: float, beat_sync: str, transition_style: str, edit_preset: str, edit_mode: str) -> tuple[list[dict], int, dict]:
    if music_path:
        music_analysis = analyze_music(music_path, music_start_seconds, target_seconds)
        save_music_analysis(str(out_dir / 'music_analysis.json'), music_analysis)
        moments = select_video_moments(video_path, target_seconds)
        save_video_moments(str(out_dir / 'video_moments.json'), moments)
        segments = build_premium_edit_plan(moments, music_analysis, target_seconds, beat_sync, transition_style, edit_preset, edit_mode)
        save_edit_plan(str(out_dir / 'edit_plan.json'), segments)
        timeline = build_debug_timeline(segments, music_analysis, edit_preset)
        save_debug_timeline(str(out_dir / 'debug_timeline.json'), timeline)
        save_debug_timeline_html(str(out_dir / 'debug_timeline.html'), timeline)
        return segments, len(music_analysis.get('beats') or []), timeline

    segments = build_segments(video_path, target_seconds)
    save_segments(str(out_dir / 'segments.json'), segments)
    timeline = {'preset': edit_preset, 'target_seconds': target_seconds, 'segments_count': len(segments), 'tracks': segments}
    save_debug_timeline(str(out_dir / 'debug_timeline.json'), timeline)
    save_debug_timeline_html(str(out_dir / 'debug_timeline.html'), timeline)
    return segments, 0, timeline


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
        edit_preset = job.get('edit_preset', 'cinematic')
        edit_mode = job.get('edit_mode', 'action')
        color_enabled = job.get('color_enabled', 'true') == 'true'
        color_preset = job.get('color_preset', 'dark_cinema')
        subtitle_enabled = job.get('subtitle_enabled', 'false') == 'true'
        subtitle_language = job.get('subtitle_language', 'auto')
        subtitle_style = job.get('subtitle_style', 'cinematic')
        centering_enabled = job.get('centering_enabled', 'true') == 'true'
        transitions_enabled = job.get('transitions_enabled', 'true') == 'true'
        transition_style = job.get('transition_style', 'glitch')
        beat_sync = job.get('beat_sync', 'strict')
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
        redis.hset(key, mapping={'render_summary': json.dumps({'platform': platform, 'target_seconds': target_seconds, 'focus_prompt': focus_prompt, 'music_enabled': bool(music_path), 'music_start_seconds': music_start_seconds, 'beat_sync': beat_sync, 'planner': 'premium_music_driven_v2', 'edit_preset': edit_preset, 'edit_mode': edit_mode, 'color_enabled': color_enabled, 'color_preset': color_preset, 'subtitle_enabled': subtitle_enabled, 'subtitle_language': subtitle_language, 'subtitle_style': subtitle_style, 'centering_enabled': centering_enabled, 'transitions_enabled': transitions_enabled, 'transition_style': transition_style, 'effects_enabled': effects_enabled, 'effect_intensity': effect_intensity, 'input_normalization': 'h264_yuv420p', 'xfade': True, 'speed_ramp': True, 'impact_zoom_shake': True}, ensure_ascii=False)})

        set_progress(redis, key, 5, 'normalizing input video')
        video_path = normalize_input_video(original_video_path, str(out_dir))
        redis.hset(key, mapping={'normalized_video_path': video_path})

        set_progress(redis, key, 18, 'building premium preset timeline')
        segments, beat_count, timeline = build_segments_for_job(video_path, music_path, out_dir, target_seconds, music_start_seconds, beat_sync, transition_style, edit_preset, edit_mode)
        if not segments:
            raise RuntimeError('premium edit planner returned zero segments')
        redis.hset(key, mapping={'edit_plan_segments': str(len(segments)), 'music_beats': str(beat_count), 'debug_timeline_path': str(out_dir / 'debug_timeline.json'), 'debug_timeline_html_path': str(out_dir / 'debug_timeline.html')})

        set_progress(redis, key, 42, f'rendering {len(segments)} premium xfade/speed-ramped segments')
        silent_path = str(out_dir / 'silent.mp4')
        render_segments_with_xfade(video_path, segments, str(out_dir / 'segments'), silent_path, color_enabled, color_preset, centering_enabled, effects_enabled, effect_intensity, transitions_enabled, transition_style)
        if not Path(silent_path).exists():
            raise RuntimeError('silent render output was not created')
        redis.hset(key, mapping={'progress': '78', 'log': 'xfade video assembled'})

        mixed_path = str(out_dir / 'mixed.mp4')
        if music_path:
            run_cmd(['ffmpeg', '-y', '-ss', str(music_start_seconds), '-stream_loop', '-1', '-i', music_path, '-i', silent_path, '-t', str(target_seconds), '-map', '1:v:0', '-map', '0:a:0', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', mixed_path])
            Path(silent_path).unlink(missing_ok=True)
        else:
            Path(silent_path).replace(mixed_path)

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
        redis.hset(key, mapping={'status': 'done', 'progress': '100', 'log': f'done, beats={beat_count}, segments={len(segments)}'})
        update_worker_heartbeat(redis, 'idle', job_id)
    except Exception as error:
        fail_job(redis, key, error)
        update_worker_heartbeat(redis, 'failed', job_id)
        raise
