from telonyx_cinema.pipeline.transition_presets import get_transition_config


def build_segment_transition_filter(style: str, enabled: bool, duration: float) -> str:
    if not enabled:
        return ''

    config = get_transition_config(style, enabled)
    raw_filter = config.get('filter') or ''
    if raw_filter:
        out_start = max(float(duration) - 0.10, 0.0)
        return raw_filter.format(out_start=round(out_start, 3))

    d = max(float(duration), 0.5)
    out_start = max(d - 0.08, 0.0)

    if style == 'flash':
        return f'curves=preset=lighter:enable=lt(t\\,0.07)+gte(t\\,{out_start})'
    if style == 'glitch':
        return f'noise=alls=22:allf=t+u:enable=lt(t\\,0.09)+gte(t\\,{out_start}),eq=contrast=1.18:saturation=1.25'
    if style == 'whip':
        return f'gblur=sigma=4:enable=lt(t\\,0.08)+gte(t\\,{out_start})'
    if style == 'tape':
        return f'noise=alls=18:allf=t+u:enable=lt(t\\,0.10)+gte(t\\,{out_start}),curves=preset=lighter:enable=lt(t\\,0.06)+gte(t\\,{out_start})'
    return ''
