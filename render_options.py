from dataclasses import dataclass


@dataclass
class RenderOptions:
    platform: str = 'shorts'
    target_seconds: int = 30
    focus_prompt: str = ''
    subtitle_enabled: bool = False
    subtitle_language: str = 'auto'
    subtitle_style: str = 'cinematic'
    color_enabled: bool = True
    color_preset: str = 'dark_cinema'
    transitions_enabled: bool = True
    transition_style: str = 'glitch'
    beat_sync: str = 'soft'
    centering_enabled: bool = True
    centering_mode: str = 'action'
    effects_enabled: bool = True
    effect_intensity: str = 'medium'


def normalize_bool(value: str | bool | None, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).lower() in ('1', 'true', 'yes', 'on')


def options_from_dict(data: dict) -> RenderOptions:
    return RenderOptions(
        platform=data.get('platform', 'shorts'),
        target_seconds=int(data.get('target_seconds', 30)),
        focus_prompt=data.get('focus_prompt', ''),
        subtitle_enabled=normalize_bool(data.get('subtitle_enabled'), False),
        subtitle_language=data.get('subtitle_language', 'auto'),
        subtitle_style=data.get('subtitle_style', 'cinematic'),
        color_enabled=normalize_bool(data.get('color_enabled'), True),
        color_preset=data.get('color_preset', 'dark_cinema'),
        transitions_enabled=normalize_bool(data.get('transitions_enabled'), True),
        transition_style=data.get('transition_style', 'glitch'),
        beat_sync=data.get('beat_sync', 'soft'),
        centering_enabled=normalize_bool(data.get('centering_enabled'), True),
        centering_mode=data.get('centering_mode', 'action'),
        effects_enabled=normalize_bool(data.get('effects_enabled'), True),
        effect_intensity=data.get('effect_intensity', 'medium'),
    )
