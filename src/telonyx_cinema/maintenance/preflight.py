import os
import subprocess
from pathlib import Path

from redis import Redis


def check_command(command: str) -> bool:
    try:
        subprocess.run([command, '-version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        return True
    except Exception:
        return False


def main() -> None:
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    storage_dir = Path(os.getenv('STORAGE_DIR', '/data/storage'))

    print('TELONYX preflight')
    print(f'ffmpeg_ok={check_command("ffmpeg")}')
    print(f'ffprobe_ok={check_command("ffprobe")}')

    try:
        redis = Redis.from_url(redis_url)
        redis.ping()
        print('redis_ok=True')
    except Exception as error:
        print(f'redis_ok=False error={error}')

    try:
        storage_dir.mkdir(parents=True, exist_ok=True)
        test_file = storage_dir / '.preflight'
        test_file.write_text('ok', encoding='utf-8')
        print(f'storage_ok={test_file.read_text(encoding="utf-8") == "ok"}')
        test_file.unlink(missing_ok=True)
    except Exception as error:
        print(f'storage_ok=False error={error}')

    for key in ['ENABLE_YOLO', 'ENABLE_BEAT_DETECT', 'ENABLE_WHISPER', 'ENABLE_CLIP', 'YOLO_MODEL', 'WHISPER_MODEL']:
        print(f'{key}={os.getenv(key, "")}')


if __name__ == '__main__':
    main()
