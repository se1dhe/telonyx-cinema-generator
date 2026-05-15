import json
from pathlib import Path


def build_debug_timeline(plan: list[dict], music_analysis: dict, preset_name: str) -> dict:
    tracks = []
    for index, item in enumerate(plan):
        tracks.append({
            'index': index,
            'timeline_start': item.get('timeline_start', 0),
            'timeline_end': round(float(item.get('timeline_start', 0)) + float(item.get('duration', 0)), 3),
            'source_start': item.get('start', 0),
            'duration': item.get('duration', 0),
            'speed': item.get('speed', 1.0),
            'role': item.get('role', 'action'),
            'impact': item.get('impact', False),
            'transition': item.get('transition_style', ''),
            'score': item.get('score', 0),
        })

    return {
        'preset': preset_name,
        'bpm': music_analysis.get('bpm'),
        'music_start_seconds': music_analysis.get('start_seconds'),
        'target_seconds': music_analysis.get('target_seconds'),
        'beats_count': len(music_analysis.get('beats') or []),
        'peak_beats_count': len(music_analysis.get('peak_beats') or []),
        'segments_count': len(plan),
        'tracks': tracks,
    }


def save_debug_timeline(path: str, timeline: dict) -> None:
    Path(path).write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding='utf-8')


def build_debug_timeline_html(timeline: dict) -> str:
    target = float(timeline.get('target_seconds') or 1)
    rows = []
    for item in timeline.get('tracks', []):
        left = max(float(item['timeline_start']) / target * 100, 0)
        width = max(float(item['duration']) / target * 100, 1)
        impact = ' impact' if item.get('impact') else ''
        rows.append(
            f'<div class="seg{impact}" style="left:{left:.2f}%;width:{width:.2f}%">'
            f'#{item["index"]} {item.get("role")} {item.get("duration")}s x{item.get("speed")}'
            f'</div>'
        )
    return f'''<!doctype html>
<html><head><meta charset="utf-8"><style>
body{{background:#05060a;color:#eee;font-family:Arial;padding:24px}}
.timeline{{position:relative;height:180px;border:1px solid #333;border-radius:16px;background:#101118;overflow:hidden}}
.seg{{position:absolute;top:30px;height:90px;background:#333;border:1px solid #777;border-radius:10px;font-size:11px;padding:8px;box-sizing:border-box;overflow:hidden}}
.seg.impact{{background:#5b123d;border-color:#ff3b8a}}
.meta{{color:#aaa;margin-bottom:16px}}
</style></head><body>
<h1>TELONYX Debug Timeline</h1>
<div class="meta">Preset: {timeline.get('preset')} | BPM: {timeline.get('bpm')} | Segments: {timeline.get('segments_count')} | Peaks: {timeline.get('peak_beats_count')}</div>
<div class="timeline">{''.join(rows)}</div>
</body></html>'''


def save_debug_timeline_html(path: str, timeline: dict) -> None:
    Path(path).write_text(build_debug_timeline_html(timeline), encoding='utf-8')
