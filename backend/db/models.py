from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from core.settings import settings


class Base(DeclarativeBase):
    pass


class JobStatus(str, enum.Enum):
    queued = 'queued'
    processing = 'processing'
    done = 'done'
    failed = 'failed'


class RenderJob(Base):
    __tablename__ = 'render_jobs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued, index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)

    focus_prompt: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_seconds: Mapped[int] = mapped_column(Integer, default=30)

    enable_subtitles: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_color: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_transitions: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_centering: Mapped[bool] = mapped_column(Boolean, default=True)

    input_video_path: Mapped[str] = mapped_column(Text)
    input_music_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    log: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
