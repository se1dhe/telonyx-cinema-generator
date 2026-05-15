def _nearest_beat_delta(duration: float, beats: list[float], min_duration: float = 1.2, max_delta: float = 0.45) -> float:
    if not beats:
        return duration
    candidates = [beat for beat in beats if min_duration <= beat <= duration + max_delta]
    if not candidates:
        return duration
    nearest = min(candidates, key=lambda beat: abs(beat - duration))
    if abs(nearest - duration) <= max_delta:
        return round(float(nearest), 3)
    return duration


def build_relative_beat_grid(beats: list[float], target_seconds: int, music_start_seconds: float = 0.0) -> list[float]:
    if not beats:
        return []
    start = max(float(music_start_seconds), 0.0)
    end = start + max(float(target_seconds), 1.0)
    relative = [round(float(beat - start), 3) for beat in beats if start < beat <= end]
    return [beat for beat in relative if beat > 0.05]


def align_segments_to_beats(segments: list[dict], beats: list[float], target_seconds: int, mode: str = 'soft') -> list[dict]:
    """
    Подгоняет длительности сегментов к музыкальной сетке.

    soft  — аккуратно двигает только длину сегмента к ближайшему биту;
    strict — сильнее режет сегменты по 2/4/6/8 битам;
    off/none — ничего не меняет.
    """
    if mode in ('off', 'none', 'false') or not beats or not segments:
        return segments

    result = []
    total = 0.0
    beat_cursor = 0.0

    for segment in segments:
        if total >= target_seconds:
            break

        original_duration = float(segment.get('duration', 1.0))
        local_beats = [beat - beat_cursor for beat in beats if beat > beat_cursor]

        if mode == 'strict':
            target_duration = _nearest_beat_delta(original_duration, local_beats, min_duration=0.9, max_delta=0.9)
        else:
            target_duration = _nearest_beat_delta(original_duration, local_beats, min_duration=1.2, max_delta=0.45)

        remaining = float(target_seconds) - total
        target_duration = min(target_duration, remaining)
        if target_duration < 0.45:
            continue

        copy = dict(segment)
        copy['duration'] = round(target_duration, 3)
        copy['beat_aligned'] = True
        result.append(copy)
        total += target_duration
        beat_cursor += target_duration

    return result or segments
