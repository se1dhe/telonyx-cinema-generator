import json
from pathlib import Path

import librosa
import numpy as np


def analyze_music(music_path: str, start_seconds: float, target_seconds: int) -> dict:
    """
    Анализирует музыку для монтажного плана.

    Возвращает:
    - bpm;
    - биты внутри выбранного окна;
    - energy curve;
    - peak beats — места, куда лучше ставить сильные кадры/переходы.
    """
    y, sr = librosa.load(music_path, sr=22050, mono=True)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    start = max(float(start_seconds), 0.0)
    end = start + max(float(target_seconds), 1.0)
    window_beats = [float(t - start) for t in beat_times if start <= float(t) <= end]

    hop_length = 512
    rms = librosa.feature.rms(y=y, hop_length=hop_length)[0]
    rms_times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    mask = (rms_times >= start) & (rms_times <= end)
    local_times = rms_times[mask] - start
    local_rms = rms[mask]

    if len(local_rms) > 0:
        normalized = (local_rms - float(np.min(local_rms))) / max(float(np.max(local_rms) - np.min(local_rms)), 1e-6)
    else:
        normalized = np.array([])

    peak_beats = []
    for beat in window_beats:
        if len(local_times) == 0:
            continue
        idx = int(np.argmin(np.abs(local_times - beat)))
        energy = float(normalized[idx]) if len(normalized) else 0.0
        if energy >= 0.62:
            peak_beats.append({'time': round(beat, 3), 'energy': round(energy, 4)})

    if len(window_beats) < 2:
        # fallback: ровная сетка 120 BPM
        step = 0.5
        window_beats = [round(t, 3) for t in np.arange(0.0, float(target_seconds) + step, step)]

    result = {
        'bpm': round(float(np.ravel(tempo)[0]), 2),
        'start_seconds': round(start, 3),
        'target_seconds': int(target_seconds),
        'beats': [round(float(t), 3) for t in window_beats],
        'peak_beats': peak_beats,
        'energy_points': [
            {'time': round(float(t), 3), 'energy': round(float(e), 4)}
            for t, e in zip(local_times[::8], normalized[::8])
        ],
    }
    return result


def save_music_analysis(path: str, analysis: dict) -> None:
    Path(path).write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding='utf-8')
