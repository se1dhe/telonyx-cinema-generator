import json
from pathlib import Path


def _beat_intervals(beats: list[float], target_seconds: int, mode: str) -> list[float]:
    if len(beats) < 2:
        return [1.0] * int(target_seconds)

    base = []
    i = 0
    while i < len(beats) - 1:
        one = beats[i + 1] - beats[i]
        if one <= 0:
            i += 1
            continue

        # Strict: много быстрых cuts. Soft: микс 1/2/4 beat blocks.
        if mode == 'strict':
            block = 1 if i % 4 in (0, 1, 2) else 2
        else:
            block = 2 if i % 5 in (0, 1, 2) else 4

        j = min(i + block, len(beats) - 1)
        duration = beats[j] - beats[i]
        if 0.35 <= duration <= 3.5:
            base.append(round(float(duration), 3))
        i = j

    result = []
    total = 0.0
    for duration in base:
        if total >= target_seconds:
            break
        remaining = target_seconds - total
        result.append(round(min(duration, remaining), 3))
        total += duration
    return result


def build_premium_edit_plan(
    moments: list[dict],
    music_analysis: dict,
    target_seconds: int,
    beat_sync: str = 'strict',
    transition_style: str = 'glitch',
) -> list[dict]:
    """
    Создаёт монтажный план из сильных видеомоментов и музыкальной сетки.

    Главное отличие от MVP:
    - длительность каждого клипа идёт от beat grid;
    - на peak beats ставятся лучшие моменты;
    - клипы чередуются, чтобы монтаж не был линейной кашей;
    - каждый сегмент получает impact flag для переходов.
    """
    beats = music_analysis.get('beats') or []
    peak_times = {round(float(item['time']), 1) for item in music_analysis.get('peak_beats', [])}
    durations = _beat_intervals(beats, target_seconds, beat_sync)
    if not durations:
        durations = [1.0] * target_seconds

    ranked = list(moments)
    if not ranked:
        ranked = [{'start': 0.0, 'duration': 1.0, 'score': 1.0}]

    # Пул: топовые моменты + немного более спокойных для дыхания.
    top = ranked[: max(8, len(ranked) // 2)]
    rest = ranked[max(8, len(ranked) // 2):] or ranked

    plan = []
    cursor = 0.0
    top_index = 0
    rest_index = 0

    for index, duration in enumerate(durations):
        if cursor >= target_seconds - 0.1:
            break

        is_peak = any(abs(cursor - peak) <= 0.22 for peak in peak_times)
        if is_peak or index % 3 != 1:
            source = top[top_index % len(top)]
            top_index += 1
        else:
            source = rest[rest_index % len(rest)]
            rest_index += 1

        source_duration = float(source.get('duration', duration))
        max_start_offset = max(source_duration - duration, 0.0)
        start = float(source.get('start', 0.0)) + min(max_start_offset, 0.25)
        final_duration = min(float(duration), float(target_seconds) - cursor)
        if final_duration < 0.35:
            continue

        plan.append({
            'start': round(start, 3),
            'duration': round(final_duration, 3),
            'timeline_start': round(cursor, 3),
            'score': source.get('score', 0),
            'impact': bool(is_peak or index % 4 == 0),
            'transition_style': transition_style,
            'beat_aligned': True,
        })
        cursor += final_duration

    return plan


def save_edit_plan(path: str, plan: list[dict]) -> None:
    Path(path).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
