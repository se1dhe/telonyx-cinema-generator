EFFECT_PRESETS = {
    'none': '',
    'low': 'noise=alls=3:allf=t+u',
    'medium': 'noise=alls=5:allf=t+u,vignette=PI/5',
    'high': 'noise=alls=7:allf=t+u,vignette=PI/4,chromashift=cbh=2:crh=-2',
}


def get_effect_filter(enabled: bool = True, intensity: str = 'medium') -> str:
    if not enabled:
        return ''
    return EFFECT_PRESETS.get(intensity, EFFECT_PRESETS['medium'])
