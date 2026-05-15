import subprocess


def probe_size(video_path: str) -> tuple[int, int]:
    process = subprocess.run(
        [
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height',
            '-of', 'csv=s=x:p=0', video_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr[-2000:])
    width, height = process.stdout.strip().split('x')
    return int(width), int(height)
