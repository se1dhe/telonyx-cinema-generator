COLOR_PRESETS = {
    'dark_cinema': 'eq=contrast=1.14:saturation=1.05:brightness=-0.025,unsharp=5:5:0.75:3:3:0.35',
    'cyberpunk_neon': 'eq=contrast=1.18:saturation=1.22:brightness=-0.015,unsharp=5:5:0.8:3:3:0.4',
    'vader_red': 'eq=contrast=1.2:saturation=1.12:brightness=-0.035,unsharp=5:5:0.85:3:3:0.45',
    'drive_night': 'eq=contrast=1.1:saturation=0.95:brightness=-0.02,unsharp=5:5:0.65:3:3:0.3',
    'neutral': 'eq=contrast=1.04:saturation=1.0:brightness=0.0',
}


def get_color_filter(preset: str, enabled: bool = True) -> str:
    if not enabled:
        return ''
    return COLOR_PRESETS.get(preset, COLOR_PRESETS['dark_cinema'])
