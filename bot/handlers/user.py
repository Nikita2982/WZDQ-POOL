from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import uuid

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message, ReplyKeyboardRemove

from bot.keyboards.menu import (
    duration_keyboard,
    genre_entry_keyboard,
    post_generation_keyboard,
    post_generation_keyboard_with_bpm,
    RAP_BPM_META,
    repeat_duration_keyboard,
    SECTION_LOADING_META,
    rap_bpm_keyboard,
    section_keyboard,
    stop_generation_keyboard,
)
from bot.services.audio_delivery import AudioDeliveryService, SECTION_ORDER
from bot.services.playlist_generator import generate_dj_playlist
from config.settings import get_settings
from database.crud import create_usage_event, get_genre_stats, get_tracks_for_genre
from database.db import SessionLocal
from subscription import CHECK_SUBSCRIPTION_CALLBACK, require_subscription

router = Router()
settings = get_settings()
audio_delivery = AudioDeliveryService()
WELCOME_IMAGE_PATH = Path(__file__).resolve().parents[2] / "assets" / "welcome.png"
RECENT_GENERATIONS: dict[int, "RecentGeneration"] = {}
ACTIVE_GENERATIONS: dict[str, "ActiveGeneration"] = {}
VISIBLE_SECTIONS = {"electronic", "house", "rap"}


@dataclass(slots=True)
class RecentGeneration:
    genre: str
    duration: int
    bpm_bucket: str | None
    track_ids: list[int]


@dataclass(slots=True)
class ActiveGeneration:
    chat_id: int
    cancelled: bool = False


class PlaylistStates(StatesGroup):
    genre = State()
    bpm_bucket = State()
    duration = State()


@router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext) -> None:
    await _log_usage_event(message.from_user, event_type="start")
    await show_playlist_entrypoint(message, state)


@router.message(Command("playlist"))
async def playlist_command_handler(message: Message, state: FSMContext) -> None:
    await show_playlist_entrypoint(message, state)


@router.callback_query(F.data == CHECK_SUBSCRIPTION_CALLBACK)
async def check_subscription_handler(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user:
        await callback.answer()
        return
    if not await require_subscription(callback.bot, callback, callback.from_user.id):
        return
    await callback.answer("Подписка подтверждена ✅")
    if callback.message:
        await callback.message.delete()
        await show_playlist_entrypoint(callback.message, state)

async def show_playlist_entrypoint(message: Message, state: FSMContext) -> None:
    await state.clear()
    _reset_recent_generation(message.chat.id)
    await state.set_state(PlaylistStates.genre)
    caption = (
        "Привет! Это <b>WZDQ PLAYLIST GENERATOR</b>\n"
        "Генератор плэйлиста на твою тусовку 🪩\n"
        "Если не успеваешь или просто лень подбирать трэки, "
        "наш бот сделает это за тебя 😉\n\n"
        "<blockquote expandable>"
        "Как пользоваться ботом:\n"
        "1. Нажми /start.\n"
        "2. Выбери нужную рубрику.\n"
        "3. Для Rap сначала выбери BPM-диапазон.\n"
        "4. Выбери тайминг: 30 или 60 минут.\n"
        "5. Дождись готовой подборки.\n\n"
        "Полная инструкция:\n"
        "1. Получи готовую подборку треков в чат.\n"
        "2. Закидывай треки в DJ-софт и играй сет.\n"
        "3. Если хочешь новую подборку, нажми Повторить генерацию.\n"
        "4. Выбери 30 или 60 минут.\n"
        "5. Бот соберет новую версию и постарается не повторять уже выданные треки.\n\n"
        "Важно:\n"
        "- Если вернуться к выбору жанра или заново нажать /start, история прошлой повторной генерации сбрасывается.\n"
        "- Тайминг считается по правилу 50% длины трека: в расчет идет половина каждого трека.\n"
        "- Иногда треков может быть меньше, если бот убрал повторы и сохранил только уникальные варианты."
        "</blockquote>"
    )
    keyboard_cleanup = await message.answer("\u2060", reply_markup=ReplyKeyboardRemove())
    photo_path = FSInputFile(WELCOME_IMAGE_PATH.as_posix())
    await message.answer_photo(photo=photo_path, caption=caption)
    await message.answer("Выбери следующий шаг", reply_markup=genre_entry_keyboard())
    await keyboard_cleanup.delete()


async def show_sections(message: Message) -> None:
    async with SessionLocal() as session:
        stats = await get_genre_stats(session)
    sections = [
        (section, stats.get(section, 0))
        for section in SECTION_ORDER
        if section in VISIBLE_SECTIONS
        if stats.get(section, 0) > 0
    ]
    await message.edit_text("Выбери раздел", reply_markup=section_keyboard(sections))


@router.callback_query(F.data == "nav:genre_entry")
async def genre_entry_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _reset_recent_generation(callback.message.chat.id)
    await state.set_state(PlaylistStates.genre)
    await show_sections(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("genre:"))
async def genre_handler(callback: CallbackQuery, state: FSMContext) -> None:
    genre = callback.data.split(":", maxsplit=1)[1]
    await state.update_data(genre=genre)
    await _log_usage_event(callback.from_user, event_type="genre_selected", genre=genre)
    if genre == "rap":
        await state.set_state(PlaylistStates.bpm_bucket)
        await callback.message.edit_text(
            "🎚 Выбери BPM-диапазон",
            reply_markup=rap_bpm_keyboard(),
        )
        await callback.answer()
        return
    await state.set_state(PlaylistStates.duration)
    await callback.message.edit_text(
        "⏱ Выбери тайминг",
        reply_markup=duration_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("rap_bpm:"))
async def rap_bpm_handler(callback: CallbackQuery, state: FSMContext) -> None:
    bpm_bucket = callback.data.split(":", maxsplit=1)[1]
    await state.update_data(bpm_bucket=bpm_bucket)
    data = await state.get_data()
    await _log_usage_event(
        callback.from_user,
        event_type="bpm_bucket_selected",
        genre=data.get("genre"),
        bpm_bucket=bpm_bucket,
    )
    await state.set_state(PlaylistStates.duration)
    await callback.message.edit_text(
        "⏱ Выбери тайминг",
        reply_markup=duration_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "nav:sections")
async def sections_nav_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _reset_recent_generation(callback.message.chat.id)
    await state.set_state(PlaylistStates.genre)
    await show_sections(callback.message)
    await callback.answer()


@router.callback_query(F.data.startswith("duration:"))
async def duration_handler(callback: CallbackQuery, state: FSMContext) -> None:
    duration = int(callback.data.split(":", maxsplit=1)[1])
    data = await state.get_data()
    genre = data.get("genre")
    if not genre:
        await callback.answer("Давай начнем заново")
        await callback.message.edit_text("Выбери раздел", reply_markup=genre_entry_keyboard())
        await state.clear()
        return
    bpm_bucket = data.get("bpm_bucket")
    await _log_usage_event(
        callback.from_user,
        event_type="duration_selected",
        genre=genre,
        bpm_bucket=bpm_bucket,
        duration=duration,
    )

    await callback.answer()
    await callback.message.delete()
    await _run_playlist_generation(
        callback.message,
        callback.bot,
        callback.message.chat.id,
        genre,
        duration,
        actor=callback.from_user,
        bpm_bucket=bpm_bucket,
    )
    await state.clear()


@router.callback_query(F.data.startswith("repeat_select:"))
async def repeat_generation_select_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _, genre, *rest = callback.data.split(":")
    bpm_bucket = rest[0] if rest else None
    await state.clear()
    await callback.answer()
    await callback.message.answer(
        "Выбери тайминг для повторной генерации",
        reply_markup=repeat_duration_keyboard(genre, bpm_bucket),
    )


@router.callback_query(F.data.startswith("repeat:"))
async def repeat_generation_handler(callback: CallbackQuery, state: FSMContext) -> None:
    _, genre, duration_raw, *rest = callback.data.split(":")
    duration = int(duration_raw)
    bpm_bucket = rest[0] if rest else None
    previous_generation = RECENT_GENERATIONS.get(callback.message.chat.id)
    await _log_usage_event(
        callback.from_user,
        event_type="generation_repeated",
        genre=genre,
        bpm_bucket=bpm_bucket,
        duration=duration,
    )
    await callback.answer()
    await callback.message.answer("Запускаем повторную генерацию. Предыдущий результат сохранен выше 👆")
    await _run_playlist_generation(
        callback.message,
        callback.bot,
        callback.message.chat.id,
        genre,
        duration,
        actor=callback.from_user,
        bpm_bucket=bpm_bucket,
        excluded_track_ids=_repeated_track_ids(previous_generation, genre, bpm_bucket),
        previous_track_count=len(previous_generation.track_ids) if previous_generation else None,
    )
    await state.clear()


@router.callback_query(F.data == "report_problem")
async def report_problem_handler(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "Если бот выдал неподходящий по жанру трек - "
        "перешли трек с указанием выбранного жанра, "
        "мы исправим проблему 🫶 @supbotwzdq"
    )


@router.callback_query(F.data.startswith("stop_gen:"))
async def stop_generation_handler(callback: CallbackQuery) -> None:
    job_id = callback.data.split(":", maxsplit=1)[1]
    job = ACTIVE_GENERATIONS.get(job_id)
    if job is not None:
        job.cancelled = True
        await _log_usage_event(callback.from_user, event_type="generation_stopped")
        await callback.message.edit_text("Генерация остановлена ⏹")
        await callback.message.answer(
            "Выбери следующий шаг",
            reply_markup=genre_entry_keyboard(),
        )
        await callback.answer("Останавливаю генерацию")
        return
    await callback.answer("Генерация уже завершена")


async def _run_playlist_generation(
    message: Message,
    bot,
    chat_id: int,
    genre: str,
    duration: int,
    *,
    actor=None,
    bpm_bucket: str | None = None,
    excluded_track_ids: set[int] | None = None,
    previous_track_count: int | None = None,
) -> None:
    job_id = uuid.uuid4().hex
    ACTIVE_GENERATIONS[job_id] = ActiveGeneration(chat_id=chat_id)
    await _log_usage_event(
        actor,
        event_type="generation_started",
        genre=genre,
        bpm_bucket=bpm_bucket,
        duration=duration,
    )
    genre_label = SECTION_LOADING_META.get(genre, genre.replace("_", " ").upper())
    if genre == "rap" and bpm_bucket:
        bucket_label = RAP_BPM_META.get(bpm_bucket, bpm_bucket)
        loading_message = await message.answer(
            f"Плейлист {genre_label} генерируется ⏳\nBPM-кластер: {bucket_label}",
            reply_markup=stop_generation_keyboard(job_id),
        )
    else:
        loading_message = await message.answer(
            f"Плейлист {genre_label} генерируется ⏳",
            reply_markup=stop_generation_keyboard(job_id),
        )

    try:
        async with SessionLocal() as session:
            tracks = await get_tracks_for_genre(session, genre)
        tracks = _filter_tracks_for_requested_bucket(tracks, genre, bpm_bucket)
        if excluded_track_ids:
            tracks = [track for track in tracks if getattr(track, "id", None) not in excluded_track_ids]

        result = generate_dj_playlist(
            tracks,
            target_duration_minutes=duration,
            strict_key_progression=bool(excluded_track_ids),
        )
        if result.tracks:
            sent_count, cancelled = await audio_delivery.send_tracks(
                bot,
                chat_id,
                result.tracks,
                should_cancel=lambda: ACTIVE_GENERATIONS.get(job_id, ActiveGeneration(chat_id, True)).cancelled,
            )
            if cancelled or ACTIVE_GENERATIONS.get(job_id, ActiveGeneration(chat_id, True)).cancelled:
                return
            RECENT_GENERATIONS[chat_id] = RecentGeneration(
                genre=genre,
                duration=duration,
                bpm_bucket=bpm_bucket,
                track_ids=[track.id for track in result.tracks if getattr(track, "id", None) is not None],
            )
            await _log_usage_event(
                actor,
                event_type="generation_completed",
                genre=genre,
                bpm_bucket=bpm_bucket,
                duration=duration,
            )
            completion_text = (
                "Генерация завершена ✅\n"
                "Просто закидывай трэки в DJ-софт и беги на сет, "
                "за все остальное мы позаботились 😉"
            )
            if excluded_track_ids and (
                result.total_duration_sec < duration * 60
                or (previous_track_count is not None and len(result.tracks) < previous_track_count)
            ):
                completion_text += (
                    "\n\nТреков меньше - но они уникальны, "
                    "убрали повторяющиеся треки 💗"
                )
            await loading_message.delete()
            await message.answer(
                completion_text,
                reply_markup=post_generation_keyboard_with_bpm(genre, duration, bpm_bucket),
            )
        else:
            await loading_message.delete()
            await message.answer(result.commentary, reply_markup=genre_entry_keyboard())
    finally:
        ACTIVE_GENERATIONS.pop(job_id, None)


def _filter_tracks_for_requested_bucket(tracks: list, genre: str, bpm_bucket: str | None) -> list:
    if genre != "rap" or not bpm_bucket:
        return tracks

    bucket_map = {
        "low_double": [(70.0, 76.0), (140.0, 152.0)],
        "mid_low": [(95.0, 103.0)],
        "mid": [(107.0, 117.0)],
        "mid_high": [(123.0, 130.0)],
    }
    ranges = bucket_map.get(bpm_bucket)
    if not ranges:
        return tracks

    filtered = []
    for track in tracks:
        bpm = getattr(track, "bpm", None)
        if bpm is None:
            continue
        if any(start <= float(bpm) <= end for start, end in ranges):
            filtered.append(track)
    return filtered


def _repeated_track_ids(
    previous_generation: RecentGeneration | None,
    genre: str,
    bpm_bucket: str | None,
) -> set[int]:
    if previous_generation is None:
        return set()
    if previous_generation.genre != genre:
        return set()
    if previous_generation.bpm_bucket != bpm_bucket:
        return set()
    return set(previous_generation.track_ids)


def _reset_recent_generation(chat_id: int) -> None:
    RECENT_GENERATIONS.pop(chat_id, None)


async def _log_usage_event(
    user,
    *,
    event_type: str,
    genre: str | None = None,
    bpm_bucket: str | None = None,
    duration: int | None = None,
) -> None:
    if user is None:
        return
    try:
        async with SessionLocal() as session:
            await create_usage_event(
                session,
                user_id=user.id,
                username=getattr(user, "username", None),
                first_name=getattr(user, "first_name", None),
                event_type=event_type,
                genre=genre,
                bpm_bucket=bpm_bucket,
                duration=duration,
            )
    except Exception:
        return
