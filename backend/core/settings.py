from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = 'TELONYX AutoEdit Web'
    app_env: str = 'local'
    app_public_base_url: str = 'http://localhost:8080'

    database_url: str = 'postgresql+psycopg://postgres:postgres@localhost:5432/telonyx_autoedit'
    redis_url: str = 'redis://localhost:6379/0'

    storage_dir: str = '/data/storage'
    yolo_model: str = 'yolov8n.pt'
    whisper_model: str = 'small'

    max_upload_mb: int = 1200
    default_target_seconds: int = 30

    @property
    def storage_path(self) -> Path:
        path = Path(self.storage_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
