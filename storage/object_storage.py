from __future__ import annotations

import logging
from pathlib import Path

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from config.settings import get_settings

logger = logging.getLogger(__name__)


class ObjectStorageService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: BaseClient | None = None

    @property
    def enabled(self) -> bool:
        return bool(
            self.settings.storage_enabled
            and self.settings.storage_bucket
            and self.settings.storage_access_key_id
            and self.settings.storage_secret_access_key
        )

    def upload_track(
        self,
        file_path: str | Path,
        *,
        file_hash: str | None,
        original_file_name: str | None,
        content_type: str | None,
    ) -> tuple[str, str] | None:
        if not self.enabled:
            return None

        path = Path(file_path)
        storage_key = self.build_track_key(file_hash=file_hash, original_file_name=original_file_name)

        extra_args: dict[str, str] = {}
        if content_type:
            extra_args["ContentType"] = content_type

        self.client.upload_file(
            path.as_posix(),
            self.settings.storage_bucket,
            storage_key,
            ExtraArgs=extra_args or None,
        )
        return self.settings.storage_bucket, storage_key

    def download_track_bytes(self, *, storage_key: str) -> bytes | None:
        if not self.enabled or not storage_key:
            return None
        try:
            response = self.client.get_object(Bucket=self.settings.storage_bucket, Key=storage_key)
        except ClientError:
            logger.warning("Storage download failed: key=%s", storage_key, exc_info=True)
            return None
        return response["Body"].read()

    def build_track_key(self, *, file_hash: str | None, original_file_name: str | None) -> str:
        suffix = Path(original_file_name or "track.mp3").suffix or ".mp3"
        safe_name = "".join(
            "_" if char in '<>:"/\\|?*' else char for char in Path(original_file_name or "track").stem
        ).strip() or "track"
        if file_hash:
            base_name = file_hash
        else:
            base_name = safe_name
        prefix = self.settings.storage_prefix.strip("/")
        key = f"{base_name[:2]}/{base_name}{suffix}" if file_hash else f"misc/{safe_name}{suffix}"
        return f"{prefix}/{key}" if prefix else key

    @property
    def client(self) -> BaseClient:
        if self._client is None:
            session = boto3.session.Session()
            self._client = session.client(
                "s3",
                endpoint_url=self.settings.storage_endpoint_url or None,
                region_name=self.settings.storage_region or None,
                aws_access_key_id=self.settings.storage_access_key_id or None,
                aws_secret_access_key=self.settings.storage_secret_access_key or None,
                use_ssl=self.settings.storage_use_ssl,
            )
        return self._client
