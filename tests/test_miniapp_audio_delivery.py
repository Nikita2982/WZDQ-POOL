import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from bot.services.audio_delivery import AudioDeliveryService


def track(number):
    return SimpleNamespace(id=number, telegram_message_id=number, storage_key=f"tracks/{number}.mp3",
                           title=f"Track {number}", artist="DJ", duration_sec=180, raw_metadata={})


def service(contents):
    result = AudioDeliveryService.__new__(AudioDeliveryService)
    result.settings = SimpleNamespace(bot_max_audio_upload_bytes=10)
    result._get_storage_track_bytes = lambda row: contents.get(row.id)
    return result


def test_cloud_delivery_preserves_set_order_and_reports_successful_uploads():
    sender = service({3: b"third", 1: b"first"})
    bot = SimpleNamespace(send_audio=AsyncMock())
    progress = AsyncMock()
    sent, cancelled = asyncio.run(sender.send_stored_tracks(bot, 42, [track(3), track(2), track(1)],
                                                          on_progress=progress))
    assert (sent, cancelled) == (2, False)
    calls = bot.send_audio.call_args_list
    assert [call.kwargs["title"] for call in calls] == ["Track 3", "Track 1"]
    assert [call.kwargs["audio"].data for call in calls] == [b"third", b"first"]
    assert [call.args[0] for call in progress.call_args_list] == [1, 2]


def test_cloud_delivery_cancels_before_sending_the_next_track():
    sender = service({1: b"one", 2: b"two"})
    bot = SimpleNamespace(send_audio=AsyncMock())
    sent, cancelled = asyncio.run(sender.send_stored_tracks(
        bot, 42, [track(1), track(2)], should_cancel=lambda: bot.send_audio.call_count > 0))
    assert (sent, cancelled) == (1, True)
    assert bot.send_audio.call_count == 1


def test_cloud_delivery_skips_oversized_files_and_continues_after_upload_failure():
    sender = service({1: b"x" * 11, 2: b"two", 3: b"three"})
    bot = SimpleNamespace(send_audio=AsyncMock(side_effect=[RuntimeError("upload failed"), None]))
    sent, cancelled = asyncio.run(sender.send_stored_tracks(bot, 42, [track(1), track(2), track(3)]))
    assert (sent, cancelled) == (1, False)
    assert bot.send_audio.call_count == 2
