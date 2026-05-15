import subprocess
from pathlib import Path

from telonyx_cinema.pipeline.smart_filters import build_smart_filter


def render_segments(
    video_path: str,
    segments: list[dict],
    work_dir: str,
    enable_color: bool,
    color_preset: str = 'dark_cinema',
    enable_centering: bool = True,
    enable_effects: bool = True,
    effect_intensity: str = 'medium',
) -> str:
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
        )
        rendered_files.append(output)

    list_path = directory / 'concat.txt'
    lines = []
    for file_path in rendered_files:
        safe_path = str(file_path).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text('\n'.join(lines), encoding='utf-8')
    return str(list_path)


def render_one_segment(
    video_path: str,
    segment: dict,
    output_path: str,
    enable_color: bool,
    color_preset: str,
    enable_centering: bool,
    enable_effects: bool,
    effect_intensity: str,
) -> None:
    vf = build_smart_filter(
        video_path=video_path,
        segment=segment,
        enable_color=enable_color,
        color_preset=color_preset,
        enable_centering=enable_centering,
        enable_effects=enable_effects,
        effect_intensity=effect_intensity,
    )
    cmd = [
        'ffmpeg', '-y', '-ss', str(segment['start']), '-t', str(segment['duration']), '-i', video_path,
        '-vf', vf, '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', output_path,
    ]
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])
