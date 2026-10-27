from __future__ import annotations

from datetime import datetime
from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from database.models import Base


class MiniAppSet(Base):
    __tablename__ = "miniapp_sets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    genre: Mapped[str] = mapped_column(String(32), nullable=False)
    duration: Mapped[int] = mapped_column(Integer, nullable=False)
    bpm_bucket: Mapped[str | None] = mapped_column(String(32), nullable=True)
    tracks: Mapped[list] = mapped_column(JSON, nullable=False)
    total_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_duration_sec: Mapped[int] = mapped_column(Integer, nullable=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(24), default="ready", nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class MiniAppYouTubeJob(Base):
    __tablename__ = "miniapp_youtube_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="running")
    progress: Mapped[str] = mapped_column(Text, nullable=False, default="Готовим анализ…")
    title: Mapped[str] = mapped_column(String(1000), nullable=False, default="DJ-сет с YouTube")
    report: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tracks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MiniAppMember(Base):
    __tablename__ = "miniapp_members"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    first_name: Mapped[str] = mapped_column(String(128), nullable=False)


class MiniAppKnowledgeVideo(Base):
    __tablename__ = "miniapp_knowledge_videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    filename: Mapped[str] = mapped_column(String(80), nullable=False)
    media_type: Mapped[str] = mapped_column(String(40), nullable=False)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
