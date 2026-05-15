from telonyx_cinema.pipeline.transition_presets import get_transition_config


def build_segment_transition_filter(style: str, enabled: bool, duration: float) -> str:
    config = get_transition_config(style, enabled)
    raw_filter = config.get('filter') or ''
    if not raw_filter:
        return ''
    out_start = max(float(duration) - 0.10, 0.0)
    return raw_filter.format(out_start=round(out_start, 3))
