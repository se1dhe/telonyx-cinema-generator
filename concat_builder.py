from pathlib import Path

from video_filters import build_video_filter


def render_segments(video_path: str, segments: list[dict], work_dir: str, enable_color: bool) -> str:
    directory = Path(work_dir)
    directory.mkdir(parents=True, exist_ok=True)
    rendered_files = []

    for index, segment in enumerate(segments):
        output = directory / f'segment_{index:03d}.mp4'
        render_one_segment(video_path, segment, str(output), enable_color)
        rendered_files.append(output)

    list_path = directory / 'concat.txt'
    lines = []
    for file_path in rendered_files:
        safe_path = str(file_path).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text('\n'.join(lines), encoding='utf-8')
    return str(list_path)


def render_one_segment(video_path: str, segment: dict, output_path: str, enable_color: bool) -> None:
    import subprocess

    cmd = [
        'ffmpeg', '-y',
        '-ss', str(segment['start']),
        '-t', str(segment['duration']),
        '-i', video_path,
        '-vf', build_video_filter(enable_color),
        '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18',
        output_path,
    ]
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-3000:])
