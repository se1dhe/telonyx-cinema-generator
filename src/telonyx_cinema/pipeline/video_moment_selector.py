import json
import subprocess
from pathlib import Path

import cv2
import numpy as np


def probe_duration(video_path: str) -> float:
    process = subprocess.run([
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'default=noprint_wrappers=1:nokey=1', video_path,
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        return float(process.stdout.strip())
    except Exception:
        return 0.0


def _score_window(video_path: str, start: float, duration: float) -> dict:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    start_frame = int(start * fps)
    frame_count = max(int(duration * fps), 1)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    prev_gray = None
    motion_values = []
    brightness_values = []
    contrast_values = []
    sharpness_values = []
    sampled = 0

    for i in range(frame_count):
        ok, frame = cap.read()
        if not ok:
            break
        if i % max(int(fps // 6), 1) != 0:
            continue
        sampled += 1
        resized = cv2.resize(frame, (320, 180))
        gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
        brightness_values.append(float(np.mean(gray)))
        contrast_values.append(float(np.std(gray)))
        sharpness_values.append(float(cv2.Laplacian(gray, cv2.CV_64F).var()))
        if prev_gray is not None:
            diff = cv2.absdiff(gray, prev_gray)
            motion_values.append(float(np.mean(diff)))
        prev_gray = gray

    cap.release()
    motion = float(np.mean(motion_values)) if motion_values else 0.0
    brightness = float(np.mean(brightness_values)) if brightness_values else 0.0
    contrast = float(np.mean(contrast_values)) if contrast_values else 0.0
    sharpness = float(np.mean(sharpness_values)) if sharpness_values else 0.0

    # Score для cinematic/action моментов: движение + контраст + резкость, но без пересвета.
    exposure_penalty = 0.0
    if brightness < 18:
        exposure_penalty = 8.0
    elif brightness > 235:
        exposure_penalty = 6.0

    score = motion * 2.1 + contrast * 0.55 + min(sharpness / 80.0, 18.0) - exposure_penalty
    return {
        'start': round(float(start), 3),
        'duration': round(float(duration), 3),
        'score': round(float(score), 4),
        'motion': round(float(motion), 4),
        'brightness': round(float(brightness), 4),
        'contrast': round(float(contrast), 4),
        'sharpness': round(float(sharpness), 4),
        'sampled_frames': sampled,
    }


def select_video_moments(video_path: str, target_seconds: int, window_seconds: float = 2.0) -> list[dict]:
    """
    Строит пул candidate moments по всему черновику.

    Это не просто scene split: мы оцениваем короткие окна по движению,
    контрасту и резкости, чтобы выбирать более сильные кадры под пики музыки.
    """
    duration = probe_duration(video_path)
    if duration <= 0:
        return [{'start': 0.0, 'duration': min(float(target_seconds), 2.0), 'score': 1.0}]

    step = max(window_seconds / 2.0, 0.75)
    moments = []
    t = 0.0
    while t < duration - 0.5:
        d = min(window_seconds, duration - t)
        if d >= 0.6:
            moments.append(_score_window(video_path, t, d))
        t += step

    moments.sort(key=lambda item: item['score'], reverse=True)

    # Убираем слишком близкие окна, чтобы не получить один и тот же момент 10 раз.
    selected = []
    min_gap = 1.25
    for moment in moments:
        if all(abs(moment['start'] - other['start']) >= min_gap for other in selected):
            selected.append(moment)
        if len(selected) >= max(int(target_seconds / 1.2), 12):
            break

    selected.sort(key=lambda item: item['score'], reverse=True)
    return selected


def save_video_moments(path: str, moments: list[dict]) -> None:
    Path(path).write_text(json.dumps(moments, ensure_ascii=False, indent=2), encoding='utf-8')
