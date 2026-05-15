from pathlib import Path

from model_config import ENABLE_BEAT_DETECT


def detect_beats(audio_path: str) -> list[float]:
    if not ENABLE_BEAT_DETECT or not audio_path:
        return []
    if not Path(audio_path).exists():
        return []

    try:
        import librosa
    except Exception:
        return []

    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
        _, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units='frames')
        beat_times = librosa.frames_to_time(beat_frames, sr=sr)
        return [round(float(t), 3) for t in beat_times]
    except Exception:
        return []


def save_beats(path: str, beats: list[float]) -> None:
    Path(path).write_text('\n'.join(str(x) for x in beats), encoding='utf-8')


def nearest_beat(beats: list[float], time_value: float) -> float:
    if not beats:
        return time_value
    return min(beats, key=lambda beat: abs(beat - time_value))
