import subprocess


def score_motion(video_path: str, start: float, duration: float) -> float:
    command = [
        'ffmpeg', '-hide_banner', '-ss', str(start), '-t', str(duration), '-i', video_path,
        '-vf', 'fps=3,scale=160:-1,format=gray,metadata=print',
        '-an', '-f', 'null', '-'
    ]
    process = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if process.returncode != 0:
        return 0.0
    text = process.stderr or ''
    frames = text.count('frame=')
    return float(max(frames, 1))
