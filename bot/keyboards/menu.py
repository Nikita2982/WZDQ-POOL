from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


SECTION_META = {
    "electronic": "⚡ Electronic",
    "house": "🏠 House",
    "rap": "🎤 Rap",
    "dance_pop": "💿 Dance / Pop",
}

SECTION_LOADING_META = {
    "electronic": "ELECTRONIC",
    "house": "HOUSE",
    "rap": "RAP",
    "dance_pop": "DANCE / POP",
}

RAP_BPM_META = {
    "low_double": "70-76 / 140-152",
    "mid_low": "95-103",
    "mid": "107-117",
    "mid_high": "123-130",
}


def genre_entry_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Выбери жанр", callback_data="nav:genre_entry")]
        ]
    )


def stop_generation_keyboard(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Остановить генерацию ⏹", callback_data=f"stop_gen:{job_id}")]
        ]
    )


def back_to_genres_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Вернуться к выбору жанра", callback_data="nav:genre_entry")]
        ]
    )


def post_generation_keyboard(genre: str, duration: int) -> InlineKeyboardMarkup:
    return post_generation_keyboard_with_bpm(genre, duration, None)


def post_generation_keyboard_with_bpm(
    genre: str,
    duration: int,
    bpm_bucket: str | None,
) -> InlineKeyboardMarkup:
    repeat_suffix = f":{bpm_bucket}" if bpm_bucket else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Повторить генерацию ⚙️",
                    callback_data=f"repeat_select:{genre}{repeat_suffix}",
                ),
                InlineKeyboardButton(text="Выбор жанра", callback_data="nav:genre_entry"),
            ]
        ]
    )


def repeat_duration_keyboard(genre: str, bpm_bucket: str | None) -> InlineKeyboardMarkup:
    repeat_suffix = f":{bpm_bucket}" if bpm_bucket else ""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="30 ⏰", callback_data=f"repeat:{genre}:30{repeat_suffix}"),
                InlineKeyboardButton(text="60 ⏰", callback_data=f"repeat:{genre}:60{repeat_suffix}"),
            ],
            [InlineKeyboardButton(text="Выбор жанра", callback_data="nav:genre_entry")],
        ]
    )


def section_keyboard(section_counts: list[tuple[str, int]]) -> InlineKeyboardMarkup:
    rows = []
    row: list[InlineKeyboardButton] = []
    for section, count in section_counts:
        label = SECTION_META.get(section, section.replace("_", " ").title())
        row.append(
            InlineKeyboardButton(
                text=label,
                callback_data=f"genre:{section}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def duration_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="30 ⏰", callback_data="duration:30"),
                InlineKeyboardButton(text="60 ⏰", callback_data="duration:60"),
            ],
            [InlineKeyboardButton(text="← Назад к разделам", callback_data="nav:sections")],
        ]
    )


def rap_bpm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=RAP_BPM_META["low_double"], callback_data="rap_bpm:low_double"),
                InlineKeyboardButton(text=RAP_BPM_META["mid_low"], callback_data="rap_bpm:mid_low"),
            ],
            [
                InlineKeyboardButton(text=RAP_BPM_META["mid"], callback_data="rap_bpm:mid"),
                InlineKeyboardButton(text=RAP_BPM_META["mid_high"], callback_data="rap_bpm:mid_high"),
            ],
            [InlineKeyboardButton(text="← Назад к разделам", callback_data="nav:sections")],
        ]
    )
