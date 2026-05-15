import json
import subprocess
from pathlib import Path

from telonyx_cinema.pipeline.motion_score import score_motion
from telonyx_cinema.pipeline.video_probe import probe_duration


def score_scene(video_path: str, start: float, duration: float) -> float:
    command = [
        'ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(duration), '-i', video_path,
        '-vf', 'select=gt(scene\\,0.08),showinfo', '-an', '-f', 'null', '-'
    ]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    text = process.stderr or ''
    return float(text.count('showinfo') + 1)


def build_segments(video_path: str, target_seconds: int) -> list[dict]:
    duration = probe_duration(video_path)
    if duration <= target_seconds:
        return [{'start': 0.0, 'duration': duration, 'score': 1.0, 'scene_score': 1.0, 'motion_score': 0.0}]

    chunk = 4.0
    segments = []
    cursor = 0.0
    while cursor < duration:
        length = min(chunk, duration - cursor)
        scene = score_scene(video_path, cursor, length)
        motion = score_motion(video_path, cursor, length)
        score = scene * 2.0 + motion
        segments.append({
            'start': round(cursor, 3),
            'duration': round(length, 3),
            'score': round(score, 4),
            'scene_score': round(scene, 4),
            'motion_score': round(motion, 4),
        })
        cursor += chunk

    segments.sort(key=lambda item: item['score'], reverse=True)
    selected = []
    total = 0.0
    for segment in segments:
        if total >= target_seconds:
            break
        selected.append(segment)
        total += segment['duration']

    selected.sort(key=lambda item: item['start'])
    return trim_segments(selected, target_seconds)


def trim_segments(segments: list[dict], target_seconds: int) -> list[dict]:
    result = []
    total = 0.0
    for segment in segments:
        if total >= target_seconds:
            break
        allowed = target_seconds - total
        length = min(float(segment['duration']), allowed)
        if length > 0.2:
            copy = dict(segment)
            copy['duration'] = round(length, 3)
            result.append(copy)
            total += length
    return result


def save_segments(path: str, segments: list[dict]) -> None:
    Path(path).write_text(json.dumps(segments, ensure_ascii=False, indent=2), encoding='utf-8')
