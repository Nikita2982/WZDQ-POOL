from __future__ import annotations

import asyncio
import logging

from config.settings import get_settings
from scanner.scan_tracks import ChannelScanner


async def main() -> None:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    summary = await ChannelScanner().scan(limit=5000)
    logging.info(
        "Full scan finished: processed=%s created=%s updated=%s",
        summary.processed_messages,
        summary.created_tracks,
        summary.updated_tracks,
    )


if __name__ == "__main__":
    asyncio.run(main())
