import subprocess
from pathlib import Path

from telonyx_cinema.pipeline.smart_filters import build_smart_filter
from telonyx_cinema.pipeline.xfade_builder import concat_with_xfade


def render_segments(
    video_path: str,
    segments: list[dict],
    work_dir: str,
    enable_color: bool,
    color_preset: str = 'dark_cinema',
    enable_centering: bool = True,
    enable_effects: bool = True,
    effect_intensity: str = 'medium',
    transitions_enabled: bool = True,
    transition_style: str = 'glitch',
) -> str:
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rendered_files = render_segment_files(
        video_path=video_path,
        segments=segments,
        work_dir=work_dir,
        enable_color=enable_color,
        color_preset=color_preset,
        enable_centering=enable_centering,
        enable_effects=enable_effects,
        effect_intensity=effect_intensity,
        transitions_enabled=transitions_enabled,
        transition_style=transition_style,
    )

    list_path = directory / 'concat.txt'
    lines = []
    for file_path in rendered_files:
        safe_path = str(file_path).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text('\n'.join(lines), encoding='utf-8')
    return str(list_path)


def render_segment_files(
    video_path: str,
    segments: list[dict],
    work_dir: str,
    enable_color: bool,
    color_preset: str = 'dark_cinema',
    enable_centering: bool = True,
    enable_effects: bool = True,
    effect_intensity: str = 'medium',
    transitions_enabled: bool = True,
    transition_style: str = 'glitch',
) -> list[Path]:
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rendered_files = []

    for index, segment in enumerate(segments):
        output = directory / f'segment_{index:03d}.mp4'
        render_one_segment(
            video_path,
            segment,
            str(output),
            enable_color,
            color_preset,
            enable_centering,
            enable_effects,
            effect_intensity,
            transitions_enabled,
            transition_style,
        )
        rendered_files.append(output)
    return rendered_files


def render_segments_with_xfade(
    video_path: str,
    segments: list[dict],
    work_dir: str,
    output_path: str,
    enable_color: bool,
    color_preset: str = 'dark_cinema',
    enable_centering: bool = True,
    enable_effects: bool = True,
    effect_intensity: str = 'medium',
    transitions_enabled: bool = True,
    transition_style: str = 'glitch',
) -> None:
    rendered_files = render_segment_files(
        video_path=video_path,
        segments=segments,
        work_dir=work_dir,
        enable_color=enable_color,
        color_preset=color_preset,
        enable_centering=enable_centering,
        enable_effects=enable_effects,
        effect_intensity=effect_intensity,
        transitions_enabled=transitions_enabled,
        transition_style=transition_style,
    )
    durations = [float(segment.get('duration', 1.0)) for segment in segments]
    xfade_duration = float(segments[0].get('xfade_duration', 0.12)) if segments else 0.12
    concat_with_xfade(rendered_files, output_path, durations, transition_style, xfade_duration)


def render_one_segment(
    video_path: str,
    segment: dict,
    output_path: str,
    enable_color: bool,
    color_preset: str,
    enable_centering: bool,
    enable_effects: bool,
    effect_intensity: str,
    transitions_enabled: bool,
    transition_style: str,
) -> None:
    vf = build_smart_filter(
        video_path=video_path,
        segment=segment,
        enable_color=enable_color,
        color_preset=color_preset,
        enable_centering=enable_centering,
        enable_effects=enable_effects,
        effect_intensity=effect_intensity,
        transitions_enabled=transitions_enabled,
        transition_style=transition_style,
    )
    speed = max(float(segment.get('speed', 1.0)), 0.2)
    source_duration = float(segment.get('source_duration', float(segment.get('duration', 1.0)) * speed))
    vf_with_speed = f'{vf},setpts=PTS/{speed}'
    cmd = [
        'ffmpeg', '-y', '-ss', str(segment['start']), '-t', str(source_duration), '-i', video_path,
        '-vf', vf_with_speed,
        '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', output_path,
    ]
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:])
