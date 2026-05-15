import shutil
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
    if style == 'hard_cut':
        return 'fade'
    return 'fade'


def _safe_xfade_duration(prev_duration: float, next_duration: float, requested: float) -> float:
    # xfade не должен быть длиннее короткого клипа, иначе FFmpeg может падать.
    limit = max(min(prev_duration, next_duration) * 0.35, 0.025)
    return round(max(min(float(requested), limit, 0.18), 0.025), 3)


def _run(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-5000:] or process.stdout[-5000:] or 'unknown ffmpeg error')


def _copy_single(input_path: Path, output_path: str) -> None:
    _run(['ffmpeg', '-y', '-i', str(input_path), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', output_path])


def _xfade_pair(prev_path: Path, next_path: Path, output_path: Path, prev_duration: float, next_duration: float, style: str, requested_xfade: float) -> float:
    transition = _transition_name(style)
    xfade = _safe_xfade_duration(prev_duration, next_duration, requested_xfade)
    offset = max(prev_duration - xfade, 0.01)

    # Только 2 входа за раз. Это сильно стабильнее на Railway, чем цепочка из 20+ xfade.
    filter_complex = (
        '[0:v]settb=AVTB,fps=30,scale=1080:1920,format=yuv420p[v0];'
        '[1:v]settb=AVTB,fps=30,scale=1080:1920,format=yuv420p[v1];'
        f'[v0][v1]xfade=transition={transition}:duration={xfade}:offset={offset:.3f},format=yuv420p[v]'
    )
    _run([
        'ffmpeg', '-y',
        '-i', str(prev_path),
        '-i', str(next_path),
        '-filter_complex', filter_complex,
        '-map', '[v]',
        '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p',
        str(output_path),
    ])
    return max(prev_duration + next_duration - xfade, 0.1)


def _concat_hard(segment_files: list[Path], output_path: str) -> None:
    list_path = Path(output_path).with_suffix('.concat.txt')
    lines = []
    for file_path in segment_files:
        safe_path = str(file_path).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    list_path.write_text('\n'.join(lines), encoding='utf-8')
    _run(['ffmpeg', '-y', '-f', 'concat', '-safe', '0', '-i', str(list_path), '-an', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '21', '-pix_fmt', 'yuv420p', output_path])


def concat_with_xfade(segment_files: list[Path], output_path: str, durations: list[float], style: str, xfade_duration: float = 0.12) -> None:
    if not segment_files:
        raise RuntimeError('No segment files for xfade concat')
    if len(segment_files) == 1:
        _copy_single(segment_files[0], output_path)
        return

    # hard_cut оставляем как стабильный concat, но с рекодом под общий формат.
    if (style or '').lower() == 'hard_cut':
        _concat_hard(segment_files, output_path)
        return

    tmp_dir = Path(output_path).with_suffix('')
    tmp_dir = tmp_dir.parent / f'{tmp_dir.name}_xfade_tmp'
    tmp_dir.mkdir(parents=True, exist_ok=True)

    current_path = segment_files[0]
    current_duration = float(durations[0])
    try:
        for index in range(1, len(segment_files)):
            next_path = segment_files[index]
            next_duration = float(durations[index]) if index < len(durations) else 1.0
            intermediate = tmp_dir / f'xfade_{index:03d}.mp4'
            current_duration = _xfade_pair(
                prev_path=current_path,
                next_path=next_path,
                output_path=intermediate,
                prev_duration=current_duration,
                next_duration=next_duration,
                style=style,
                requested_xfade=xfade_duration,
            )
            current_path = intermediate

        shutil.copyfile(current_path, output_path)
    except Exception as error:
        # Fallback: лучше получить готовый ролик с hard cuts, чем failed job.
        _concat_hard(segment_files, output_path)
        fallback_note = Path(output_path).with_suffix('.xfade_fallback.txt')
        fallback_note.write_text(str(error)[-5000:], encoding='utf-8')
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
