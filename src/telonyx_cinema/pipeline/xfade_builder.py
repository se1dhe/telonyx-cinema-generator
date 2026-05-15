import subprocess
from pathlib import Path


def _transition_name(style: str) -> str:
    style = (style or 'fade').lower()
    if style in ('flash', 'glitch'):
        return 'fadefast'
    if style == 'whip':
        return 'wipeleft'
    if style == 'tape':
        return 'dissolve'
    return 'fade'


def concat_with_xfade(segment_files: list[Path], output_path: str, durations: list[float], style: str, xfade_duration: float = 0.12) -> None:
    if not segment_files:
        raise RuntimeError('No segment files for xfade concat')
    if len(segment_files) == 1:
        process = subprocess.run(['ffmpeg', '-y', '-i', str(segment_files[0]), '-c', 'copy', output_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if process.returncode != 0:
            raise RuntimeError(process.stderr[-3000:])
        return

    transition = _transition_name(style)
    xfade = max(min(float(xfade_duration), 0.25), 0.04)
    inputs = []
    for file in segment_files:
        inputs.extend(['-i', str(file)])

    filters = []
    cumulative = float(durations[0])
    previous = '[0:v]'
    for index in range(1, len(segment_files)):
        offset = max(cumulative - xfade, 0.01)
        out_label = f'[x{index}]'
        filters.append(f'{previous}[{index}:v]xfade=transition={transition}:duration={xfade}:offset={offset:.3f}{out_label}')
        previous = out_label
        cumulative += float(durations[index]) - xfade

    filter_complex = ';'.join(filters)
    cmd = [
        'ffmpeg', '-y', *inputs,
        '-filter_complex', filter_complex,
        '-map', previous,
        '-an', '-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p',
        output_path,
    ]
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:])
