import os
import shutil
import time
from pathlib import Path

STORAGE_DIR = Path(os.getenv('STORAGE_DIR', '/data/storage'))
MAX_JOB_AGE_HOURS = int(os.getenv('MAX_JOB_AGE_HOURS', '48'))


def cleanup_storage() -> dict:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    now = time.time()
    max_age = MAX_JOB_AGE_HOURS * 3600
    removed = []
    kept = []

    for path in STORAGE_DIR.iterdir():
        if not path.is_dir():
            continue
        age = now - path.stat().st_mtime
        if age > max_age:
            shutil.rmtree(path, ignore_errors=True)
            removed.append(path.name)
        else:
            kept.append(path.name)

    return {'storage_dir': str(STORAGE_DIR), 'max_job_age_hours': MAX_JOB_AGE_HOURS, 'removed': removed, 'kept': kept}


def main() -> None:
    print(cleanup_storage())


if __name__ == '__main__':
    main()
