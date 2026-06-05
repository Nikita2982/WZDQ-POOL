from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from config.settings import get_settings
from database.crud import fix_track_mix_data, get_genre_stats, get_usage_summary, mark_track_unsuitable
from database.db import SessionLocal
from scanner.scan_tracks import ChannelScanner

router = Router()
settings = get_settings()


def _is_admin(message: Message) -> bool:
    return bool(message.from_user and message.from_user.id in settings.admin_user_ids)


@router.message(Command("scan_channel"))
async def scan_channel_handler(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда доступна только администратору.")
        return
    await message.answer("Запускаю сканирование канала. Это может занять несколько минут.")
    summary = await ChannelScanner().scan()
    await message.answer(
        f"Сканирование завершено.\n"
        f"Обработано сообщений: {summary.processed_messages}\n"
        f"Создано треков: {summary.created_tracks}\n"
        f"Обновлено треков: {summary.updated_tracks}"
    )


@router.message(Command("stats"))
async def stats_handler(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда доступна только администратору.")
        return
    async with SessionLocal() as session:
        stats = await get_genre_stats(session)
    if not stats:
        await message.answer("База пока пустая.")
        return
    lines = ["Треки по жанрам:"]
    lines.extend(f"- {genre}: {count}" for genre, count in stats.items())
    await message.answer("\n".join(lines))


@router.message(Command("mark_unsuitable"))
async def mark_unsuitable_handler(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда доступна только администратору.")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("Использование: /mark_unsuitable <track_id>")
        return
    async with SessionLocal() as session:
        track = await mark_track_unsuitable(session, int(parts[1]))
    await message.answer("Трек обновлен." if track else "Трек не найден.")


@router.message(Command("fix_track"))
async def fix_track_handler(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда доступна только администратору.")
        return
    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer("Использование: /fix_track <track_id> <bpm> <camelot_key> [musical_key]")
        return
    track_id = int(parts[1])
    bpm = float(parts[2])
    camelot_key = parts[3].upper()
    musical_key = " ".join(parts[4:]) if len(parts) > 4 else None
    async with SessionLocal() as session:
        track = await fix_track_mix_data(
            session,
            track_id,
            bpm=bpm,
            camelot_key=camelot_key,
            musical_key=musical_key,
        )
    await message.answer("Mix-данные обновлены." if track else "Трек не найден.")


@router.message(Command("admin_stats"))
async def admin_stats_handler(message: Message) -> None:
    if not _is_admin(message):
        await message.answer("Эта команда доступна только администратору.")
        return
    async with SessionLocal() as session:
        summary = await get_usage_summary(session)
    lines = [
        "Статистика использования бота:",
        f"Всего событий: {summary.total_events}",
        f"Уникальных пользователей: {summary.unique_users}",
        f"Успешных генераций: {summary.completed_generations}",
    ]
    if summary.top_users:
        lines.append("")
        lines.append("Топ пользователей:")
        for row in summary.top_users:
            label = f"@{row.username}" if row.username else (row.first_name or f"user_{row.user_id}")
            lines.append(f"- {label}: {row.completed_count}")
    if summary.top_genres:
        lines.append("")
        lines.append("Популярные жанры:")
        for row in summary.top_genres:
            lines.append(f"- {row.genre}: {row.completed_count}")
    await message.answer("\n".join(lines))
