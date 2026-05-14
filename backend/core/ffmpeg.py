from __future__ import annotations

import subprocess


def run(cmd: list[str]) -> None:
    process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-4000:])


def ffprobe_duration(path: str) -> float:
    process = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr)
    return float(process.stdout.strip())


def extract_audio_wav(input_video: str, output_wav: str) -> None:
    run(['ffmpeg', '-y', '-i', input_video, '-vn', '-ac', '1', '-ar', '16000', output_wav])
