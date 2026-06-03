from functools import lru_cache
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(alias="TELEGRAM_BOT_TOKEN")
    telegram_api_id: int = Field(alias="TELEGRAM_API_ID")
    telegram_api_hash: str = Field(alias="TELEGRAM_API_HASH")
    telethon_session_name: str = Field(default="dj_ai_bot", alias="TELETHON_SESSION_NAME")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    source_chat: str | int = Field(alias="SOURCE_CHAT")
    subscription_channel_id: str | int = Field(default="", alias="CHANNEL_ID")
    default_scan_limit: int = Field(default=500, alias="DEFAULT_SCAN_LIMIT")
    supported_genres_raw: str = Field(
        default="afro_house,melodic_techno,tech_house,organic_house,progressive_house,deep_house",
        alias="SUPPORTED_GENRES",
    )
    genre_hashtag_prefix: str = Field(default="#", alias="GENRE_HASHTAG_PREFIX")
    admin_user_ids_raw: str = Field(default="", alias="ADMIN_USER_IDS")

    api_host: str = Field(default="0.0.0.0", alias="API_HOST")
    api_port: int = Field(default=8080, alias="API_PORT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    temp_audio_dir: Path = Field(default=Path("/tmp/dj_ai_bot"), alias="TEMP_AUDIO_DIR")
    enable_zip_export: bool = Field(default=False, alias="ENABLE_ZIP_EXPORT")
    storage_enabled: bool = Field(default=False, alias="STORAGE_ENABLED")
    storage_endpoint_url: str = Field(default="", alias="STORAGE_ENDPOINT_URL")
    storage_access_key_id: str = Field(default="", alias="STORAGE_ACCESS_KEY_ID")
    storage_secret_access_key: str = Field(default="", alias="STORAGE_SECRET_ACCESS_KEY")
    storage_bucket: str = Field(default="", alias="STORAGE_BUCKET")
    storage_region: str = Field(default="", alias="STORAGE_REGION")
    storage_prefix: str = Field(default="tracks", alias="STORAGE_PREFIX")
    storage_use_ssl: bool = Field(default=True, alias="STORAGE_USE_SSL")

    @computed_field
    @property
    def supported_genres(self) -> list[str]:
        return [item.strip().lower() for item in self.supported_genres_raw.split(",") if item.strip()]

    @computed_field
    @property
    def admin_user_ids(self) -> set[int]:
        return {
            int(item.strip())
            for item in self.admin_user_ids_raw.split(",")
            if item.strip()
        }


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.temp_audio_dir.mkdir(parents=True, exist_ok=True)
    return settings
