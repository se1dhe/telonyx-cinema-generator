import os
from pathlib import Path

from fastapi import HTTPException, UploadFile

MAX_UPLOAD_MB = int(os.getenv('MAX_UPLOAD_MB', '1200'))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.m4v', '.webm', '.mkv'}
AUDIO_EXTENSIONS = {'.mp3', '.wav', '.m4a', '.aac', '.ogg', '.flac'}


def validate_upload_file(file: UploadFile, allowed_extensions: set[str], label: str) -> None:
    suffix = Path(file.filename or '').suffix.lower()
    if suffix not in allowed_extensions:
        raise HTTPException(status_code=400, detail=f'{label} has unsupported file extension: {suffix}')

    size = getattr(file, 'size', None)
    if size is not None and int(size) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f'{label} is too large. Max upload size is {MAX_UPLOAD_MB} MB')


def validate_video_upload(file: UploadFile) -> None:
    validate_upload_file(file, VIDEO_EXTENSIONS, 'Video')


def validate_audio_upload(file: UploadFile) -> None:
    validate_upload_file(file, AUDIO_EXTENSIONS, 'Music')


def ensure_saved_size(path: Path, label: str) -> None:
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        path.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=f'{label} is too large. Max upload size is {MAX_UPLOAD_MB} MB')
