import os
from pathlib import Path

from redis import Redis

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
STORAGE_DIR = Path(os.getenv('STORAGE_DIR', '/data/storage'))


def diagnostics_handler():
    redis_ok = False
    redis_error = ''
    try:
        redis = Redis.from_url(REDIS_URL)
        redis.ping()
        redis_ok = True
    except Exception as error:
        redis_error = str(error)[-1000:]

    storage_ok = False
    storage_error = ''
    try:
        STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        test_file = STORAGE_DIR / '.diagnostics_write_test'
        test_file.write_text('ok', encoding='utf-8')
        storage_ok = test_file.read_text(encoding='utf-8') == 'ok'
        test_file.unlink(missing_ok=True)
    except Exception as error:
        storage_error = str(error)[-1000:]

    return {
        'service': 'api',
        'redis_ok': redis_ok,
        'redis_error': redis_error,
        'storage_dir': str(STORAGE_DIR),
        'storage_ok': storage_ok,
        'storage_error': storage_error,
        'env': {
            'ENABLE_YOLO': os.getenv('ENABLE_YOLO', ''),
            'ENABLE_BEAT_DETECT': os.getenv('ENABLE_BEAT_DETECT', ''),
            'ENABLE_WHISPER': os.getenv('ENABLE_WHISPER', ''),
            'ENABLE_CLIP': os.getenv('ENABLE_CLIP', ''),
            'MODEL_DEVICE': os.getenv('MODEL_DEVICE', ''),
            'COMPUTE_TYPE': os.getenv('COMPUTE_TYPE', ''),
            'YOLO_MODEL': os.getenv('YOLO_MODEL', ''),
            'WHISPER_MODEL': os.getenv('WHISPER_MODEL', ''),
        },
    }
