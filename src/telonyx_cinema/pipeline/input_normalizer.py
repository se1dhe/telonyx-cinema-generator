import subprocess
from pathlib import Path


def run_ffmpeg(cmd: list[str]) -> tuple[bool, str]:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    output = (process.stderr or process.stdout or '')[-5000:]
    return process.returncode == 0, output


def normalize_input_video(input_path: str, work_dir: str) -> str:
    """
    Нормализует любое входное видео в безопасный H.264 yuv420p.

    Это нужно для Railway/CPU окружения, потому что пользовательские файлы часто
    приходят в AV1/HEVC/нестандартных pixel format, а OpenCV и FFmpeg-фильтры
    потом падают на декодировании.
    """
    source = Path(input_path)
    output = Path(work_dir) / 'normalized_input.mp4'
    output.parent.mkdir(parents=True, exist_ok=True)

    # Первая попытка: явно используем libdav1d для AV1, если он доступен в ffmpeg.
    libdav1d_cmd = [
        'ffmpeg', '-y',
        '-hwaccel', 'none',
        '-c:v', 'libdav1d',
        '-i', str(source),
        '-map', '0:v:0',
        '-map', '0:a?',
        '-vf', 'fps=30,format=yuv420p',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '20',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        str(output),
    ]
    ok, error = run_ffmpeg(libdav1d_cmd)
    if ok and output.exists() and output.stat().st_size > 0:
        return str(output)

    # Вторая попытка: обычный software decode без принудительного decoder.
    generic_cmd = [
        'ffmpeg', '-y',
        '-hwaccel', 'none',
        '-i', str(source),
        '-map', '0:v:0',
        '-map', '0:a?',
        '-vf', 'fps=30,format=yuv420p',
        '-c:v', 'libx264',
        '-preset', 'veryfast',
        '-crf', '20',
        '-c:a', 'aac',
        '-b:a', '128k',
        '-movflags', '+faststart',
        str(output),
    ]
    ok, generic_error = run_ffmpeg(generic_cmd)
    if ok and output.exists() and output.stat().st_size > 0:
        return str(output)

    raise RuntimeError(f'Input video normalization failed. libdav1d attempt: {error}\nGeneric attempt: {generic_error}')
