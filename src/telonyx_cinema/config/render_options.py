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


def options_to_redis_mapping(options: RenderOptions) -> dict[str, str]:
    return {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in options.__dict__.items()}
