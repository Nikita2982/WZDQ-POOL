from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Track(Base):
    __tablename__ = "tracks"
    __table_args__ = (
        UniqueConstraint("telegram_channel_id", "telegram_message_id", name="uq_track_channel_message"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_message_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    telegram_file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_channel_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    genre: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    artist: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_sec: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bpm: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    musical_key: Mapped[str | None] = mapped_column(String(32), nullable=True)
    camelot_key: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    energy_level: Mapped[float | None] = mapped_column(Float, nullable=True)
    file_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_link: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_suitable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    suitability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ScanJob(Base):
    __tablename__ = "scan_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_chat: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False, index=True)
    processed_messages: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_tracks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_tracks: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
