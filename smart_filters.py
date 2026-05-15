from color_presets import get_color_filter
from crop_math import crop_x_expr
from focus_detector import detect_focus_center
from video_probe import probe_size


def build_smart_filter(video_path: str, segment: dict, enable_color: bool, color_preset: str = 'dark_cinema') -> str:
    width, height = probe_size(video_path)
    center = detect_focus_center(video_path, float(segment['start']), float(segment['duration']))
    if center is None:
        center_x = width / 2.0
    else:
        center_x = center[0]

    crop_x = crop_x_expr(width, height, center_x)
    crop_w = int(height * 9 / 16)
    if crop_w > width:
        base = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920'
    else:
        base = f'crop={crop_w}:{height}:{crop_x}:0,scale=1080:1920'

    color = get_color_filter(color_preset, enable_color)
    if color:
        return base + ',' + color
    return base
