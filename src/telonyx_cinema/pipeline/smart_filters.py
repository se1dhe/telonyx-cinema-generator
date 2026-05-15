from telonyx_cinema.pipeline.color_presets import get_color_filter
from telonyx_cinema.pipeline.crop_math import crop_x_expr
from telonyx_cinema.pipeline.effect_presets import get_effect_filter
from telonyx_cinema.pipeline.focus_detector import detect_focus_center
from telonyx_cinema.pipeline.segment_effects import build_segment_transition_filter
from telonyx_cinema.pipeline.video_probe import probe_size


def build_impact_filter(segment: dict) -> str:
    if not segment.get('impact'):
        return ''
    role = segment.get('role', 'action')
    if role in ('intro', 'dialogue'):
        return ''
    # Лёгкий punch-in + shake в первые 140 мс сегмента.
    return "scale='1080+36*between(t,0,0.14)':'1920+64*between(t,0,0.14)',crop=1080:1920:'18*between(t,0,0.14)*sin(90*t)':'32*between(t,0,0.14)*cos(75*t)'"


def build_smart_filter(
    video_path: str,
    segment: dict,
    enable_color: bool,
    color_preset: str = 'dark_cinema',
    enable_centering: bool = True,
    enable_effects: bool = True,
    effect_intensity: str = 'medium',
    transitions_enabled: bool = True,
    transition_style: str = 'glitch',
) -> str:
    width, height = probe_size(video_path)
    center_x = width / 2.0

    if enable_centering:
        center = detect_focus_center(video_path, float(segment['start']), float(segment.get('source_duration', segment['duration'])))
        if center is not None:
            center_x = center[0]

    crop_x = crop_x_expr(width, height, center_x)
    crop_w = int(height * 9 / 16)
    if crop_w > width:
        filters = ['scale=1080:1920:force_original_aspect_ratio=increase', 'crop=1080:1920']
    else:
        filters = [f'crop={crop_w}:{height}:{crop_x}:0', 'scale=1080:1920']

    impact = build_impact_filter(segment)
    color = get_color_filter(color_preset, enable_color)
    effect = get_effect_filter(enable_effects, effect_intensity)
    transition = build_segment_transition_filter(transition_style, transitions_enabled, float(segment.get('duration', 1.0)))

    if impact:
        filters.append(impact)
    if color:
        filters.append(color)
    if effect:
        filters.append(effect)
    if transition:
        filters.append(transition)
    filters.append('fps=30')
    filters.append('format=yuv420p')
    return ','.join(filters)
