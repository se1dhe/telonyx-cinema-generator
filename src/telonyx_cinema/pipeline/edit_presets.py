PRESETS = {
    'aggressive': {
        'name': 'Aggressive',
        'beat_sync': 'strict',
        'transition_style': 'glitch',
        'effect_intensity': 'high',
        'color_preset': 'vader_red',
        'cut_pattern': [1, 1, 1, 2, 1, 1, 2, 4],
        'speed_pattern': [1.0, 1.08, 1.18, 0.92, 1.0, 1.12],
        'impact_every': 2,
        'xfade_duration': 0.10,
        'intro_seconds': 2.2,
        'dialogue_hold_seconds': 3.0,
    },
    'cinematic': {
        'name': 'Cinematic',
        'beat_sync': 'soft',
        'transition_style': 'flash',
        'effect_intensity': 'medium',
        'color_preset': 'dark_cinema',
        'cut_pattern': [2, 2, 4, 2, 2, 4],
        'speed_pattern': [1.0, 0.96, 1.04, 1.0],
        'impact_every': 4,
        'xfade_duration': 0.14,
        'intro_seconds': 3.2,
        'dialogue_hold_seconds': 4.0,
    },
    'sad': {
        'name': 'Sad / Loneliness',
        'beat_sync': 'soft',
        'transition_style': 'tape',
        'effect_intensity': 'low',
        'color_preset': 'drive_night',
        'cut_pattern': [4, 4, 2, 4, 2],
        'speed_pattern': [0.88, 0.92, 0.96, 1.0],
        'impact_every': 5,
        'xfade_duration': 0.18,
        'intro_seconds': 4.0,
        'dialogue_hold_seconds': 4.5,
    },
    'cyberpunk': {
        'name': 'Cyberpunk Neon',
        'beat_sync': 'strict',
        'transition_style': 'glitch',
        'effect_intensity': 'high',
        'color_preset': 'cyberpunk_neon',
        'cut_pattern': [1, 2, 1, 2, 4, 1, 1, 2],
        'speed_pattern': [1.0, 1.1, 0.9, 1.16, 1.0],
        'impact_every': 3,
        'xfade_duration': 0.11,
        'intro_seconds': 2.8,
        'dialogue_hold_seconds': 3.6,
    },
}


def get_edit_preset(name: str | None) -> dict:
    key = (name or 'cinematic').lower().strip()
    return PRESETS.get(key, PRESETS['cinematic'])


def preset_names() -> list[str]:
    return list(PRESETS.keys())
