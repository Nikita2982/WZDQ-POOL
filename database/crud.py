from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import Select, func, not_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import ScanJob, Track


async def create_scan_job(session: AsyncSession, source_chat: str) -> ScanJob:
    job = ScanJob(source_chat=source_chat, status="running")
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def finish_scan_job(
    session: AsyncSession,
    job: ScanJob,
    *,
    processed_messages: int,
    created_tracks: int,
    updated_tracks: int,
    error_message: str | None = None,
) -> ScanJob:
    if error_message:
        await session.rollback()
    job.processed_messages = processed_messages
    job.created_tracks = created_tracks
    job.updated_tracks = updated_tracks
    job.finished_at = datetime.now(timezone.utc)
    job.status = "failed" if error_message else "finished"
    job.error_message = error_message
    await session.commit()
    await session.refresh(job)
    return job


async def get_track_by_message(
    session: AsyncSession,
    channel_id: str,
    message_id: int,
) -> Track | None:
    result = await session.execute(
        select(Track).where(
            Track.telegram_channel_id == channel_id,
            Track.telegram_message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


async def get_max_track_message_id(
    session: AsyncSession,
    channel_id: str,
) -> int | None:
    result = await session.execute(
        select(func.max(Track.telegram_message_id)).where(Track.telegram_channel_id == channel_id)
    )
    return result.scalar_one()


async def get_track_by_file_hash(
    session: AsyncSession,
    file_hash: str | None,
) -> Track | None:
    if not file_hash:
        return None
    result = await session.execute(select(Track).where(Track.file_hash == file_hash))
    return result.scalar_one_or_none()


async def upsert_track(session: AsyncSession, payload: dict) -> tuple[Track, bool]:
    track = await get_track_by_message(
        session,
        channel_id=payload["telegram_channel_id"],
        message_id=payload["telegram_message_id"],
    )
    if track is None:
        track = await get_track_by_file_hash(session, payload.get("file_hash"))
    created = track is None
    if track is None:
        track = Track(**payload)
        session.add(track)
    else:
        for key, value in payload.items():
            setattr(track, key, value)
    await session.commit()
    await session.refresh(track)
    return track, created


async def get_tracks_for_genre(session: AsyncSession, genre: str) -> list[Track]:
    result = await session.execute(
        select(Track)
        .where(
            Track.genre == genre,
            Track.is_suitable.is_(True),
            not_(func.lower(Track.title).like("%acapella%")),
            not_(func.lower(Track.title).like("%scratch%")),
            not_(func.lower(Track.title).like("%sample%")),
        )
        .order_by(Track.bpm.asc().nullslast(), Track.energy_level.asc().nullslast())
    )
    return list(result.scalars().all())


async def get_genre_stats(session: AsyncSession) -> dict[str, int]:
    result = await session.execute(
        select(Track.genre, func.count(Track.id)).group_by(Track.genre).order_by(Track.genre.asc())
    )
    stats = defaultdict(int)
    for genre, count in result.all():
        stats[genre] = count
    return dict(stats)


async def list_tracks(session: AsyncSession, limit: int = 100) -> list[Track]:
    result = await session.execute(select(Track).order_by(Track.created_at.desc()).limit(limit))
    return list(result.scalars().all())


async def mark_track_unsuitable(session: AsyncSession, track_id: int) -> Track | None:
    track = await session.get(Track, track_id)
    if track is None:
        return None
    track.is_suitable = False
    await session.commit()
    await session.refresh(track)
    return track


async def fix_track_mix_data(
    session: AsyncSession,
    track_id: int,
    *,
    bpm: float,
    camelot_key: str,
    musical_key: str | None = None,
) -> Track | None:
    track = await session.get(Track, track_id)
    if track is None:
        return None
    track.bpm = bpm
    track.camelot_key = camelot_key
    if musical_key:
        track.musical_key = musical_key
    await session.commit()
    await session.refresh(track)
    return track
