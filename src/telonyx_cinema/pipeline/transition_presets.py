TRANSITION_PRESETS = {
    'hard_cut': {'overlap': 0.0, 'filter': ''},
    'flash': {'overlap': 0.18, 'filter': 'fade=t=in:st=0:d=0.08,fade=t=out:st={out_start}:d=0.08'},
    'glitch': {'overlap': 0.12, 'filter': 'tblend=all_mode=lighten,noise=alls=8:allf=t+u'},
    'whip': {'overlap': 0.10, 'filter': 'gblur=sigma=1.5'},
    'tape': {'overlap': 0.16, 'filter': 'noise=alls=10:allf=t+u,curves=preset=lighter'},
}


def get_transition_config(style: str, enabled: bool = True) -> dict:
    if not enabled:
        return TRANSITION_PRESETS['hard_cut']
    return TRANSITION_PRESETS.get(style, TRANSITION_PRESETS['glitch'])
