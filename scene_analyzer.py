import json
import subprocess
from pathlib import Path


def probe_duration(video_path: str) -> float:
    process = subprocess.run(
        ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', video_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-2000:])
    return float(process.stdout.strip())


def build_segments(video_path: str, target_seconds: int) -> list[dict]:
    duration = probe_duration(video_path)
    if duration <= target_seconds:
        return [{'start': 0.0, 'duration': duration, 'score': 1.0}]

    chunk = 4.0
    segments = []
    cursor = 0.0
    while cursor < duration:
        remaining = duration - cursor
        length = min(chunk, remaining)
        score = score_segment(video_path, cursor, length)
        segments.append({'start': round(cursor, 3), 'duration': round(length, 3), 'score': score})
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


def score_segment(video_path: str, start: float, duration: float) -> float:
    command = [
        'ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(duration), '-i', video_path,
        '-vf', 'select=gt(scene\\,0.08),showinfo', '-an', '-f', 'null', '-'
    ]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    text = process.stderr or ''
    scene_hits = text.count('showinfo')
    return float(scene_hits + 1)


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
