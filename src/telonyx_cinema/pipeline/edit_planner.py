import json
from pathlib import Path

from telonyx_cinema.pipeline.edit_presets import get_edit_preset


def _beat_intervals(beats: list[float], target_seconds: int, preset: dict) -> list[float]:
    if len(beats) < 2:
        return [1.0] * int(target_seconds)

    pattern = preset.get('cut_pattern') or [2, 2, 4]
    result = []
    i = 0
    p = 0
    total = 0.0

    while i < len(beats) - 1 and total < target_seconds:
        block = int(pattern[p % len(pattern)])
        j = min(i + block, len(beats) - 1)
        duration = beats[j] - beats[i]
        if 0.28 <= duration <= 4.8:
            remaining = float(target_seconds) - total
            clipped = round(min(float(duration), remaining), 3)
            if clipped >= 0.28:
                result.append(clipped)
                total += clipped
        i = j
        p += 1

    return result


def _segment_role(index: int, cursor: float, source: dict, preset: dict, mode: str) -> str:
    if mode == 'dialogue':
        if cursor < float(preset.get('dialogue_hold_seconds', 3.5)):
            return 'dialogue'
    if mode == 'intro' or mode == 'dialogue':
        if cursor < float(preset.get('intro_seconds', 3.0)):
            return 'intro'
    if source.get('motion', 0) < 3.0 and source.get('contrast', 0) > 20:
        return 'mood'
    return 'action'


def build_premium_edit_plan(
    moments: list[dict],
    music_analysis: dict,
    target_seconds: int,
    beat_sync: str = 'strict',
    transition_style: str = 'glitch',
    preset_name: str = 'cinematic',
    edit_mode: str = 'action',
) -> list[dict]:
    preset = get_edit_preset(preset_name)
    beats = music_analysis.get('beats') or []
    peak_times = {round(float(item['time']), 1) for item in music_analysis.get('peak_beats', [])}
    durations = _beat_intervals(beats, target_seconds, preset)
    if not durations:
        durations = [1.0] * target_seconds

    ranked = list(moments)
    if not ranked:
        ranked = [{'start': 0.0, 'duration': 1.0, 'score': 1.0, 'motion': 0, 'contrast': 0}]

    top = ranked[: max(8, len(ranked) // 2)]
    rest = ranked[max(8, len(ranked) // 2):] or ranked
    speed_pattern = preset.get('speed_pattern') or [1.0]
    impact_every = max(int(preset.get('impact_every', 4)), 1)

    plan = []
    cursor = 0.0
    top_index = 0
    rest_index = 0

    for index, duration in enumerate(durations):
        if cursor >= target_seconds - 0.1:
            break

        is_peak = any(abs(cursor - peak) <= 0.24 for peak in peak_times)
        if is_peak or index % 3 != 1:
            source = top[top_index % len(top)]
            top_index += 1
        else:
            source = rest[rest_index % len(rest)]
            rest_index += 1

        role = _segment_role(index, cursor, source, preset, edit_mode)
        speed = float(speed_pattern[index % len(speed_pattern)])
        if role in ('intro', 'dialogue'):
            speed = min(speed, 1.0)
        if is_peak and role == 'action':
            speed = max(speed, 1.08)

        timeline_duration = min(float(duration), float(target_seconds) - cursor)
        source_duration = max(timeline_duration * speed, 0.35)
        source_window_duration = float(source.get('duration', source_duration))
        max_start_offset = max(source_window_duration - source_duration, 0.0)
        start = float(source.get('start', 0.0)) + min(max_start_offset, 0.25)

        if timeline_duration < 0.28:
            continue

        impact = bool(is_peak or index % impact_every == 0)
        plan.append({
            'start': round(start, 3),
            'duration': round(timeline_duration, 3),
            'source_duration': round(source_duration, 3),
            'timeline_start': round(cursor, 3),
            'score': source.get('score', 0),
            'motion': source.get('motion', 0),
            'contrast': source.get('contrast', 0),
            'impact': impact,
            'speed': round(speed, 3),
            'role': role,
            'transition_style': transition_style,
            'xfade_duration': float(preset.get('xfade_duration', 0.12)),
            'beat_aligned': True,
        })
        cursor += timeline_duration

    return plan


def save_edit_plan(path: str, plan: list[dict]) -> None:
    Path(path).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
