"""The two storage backends.

``LocalStorage`` is not a stub. It is the backend the zero-setup path uses, so
it gets the same care as the blob one: atomic writes, traversal-proof keys, and
a size cap. A "development only" backend that corrupts a file on a crash is a
development-only bug you then chase in production.
"""

from __future__ import annotations

import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from app.core.logging import get_logger
from app.storage.base import (
    ArtifactRef,
    StorageError,
    guess_content_type,
    validate_key,
)

log = get_logger(__name__)

#: 8MB. A matplotlib PNG is tens of kilobytes; anything approaching this is a
#: bug or an attack, and rejecting it here keeps both out of storage entirely.
MAX_OBJECT_BYTES = 8 * 1024 * 1024


class LocalStorage:
    """Files under a directory. The default, and genuinely used."""

    name = "local"

    def __init__(self, root: Path, url_prefix: str = "/api/v1/artifacts") -> None:
        self.root = root.resolve()
        self.url_prefix = url_prefix.rstrip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self.root / key).resolve()
        # Belt and braces over validate_key: resolve() collapses any traversal
        # the pattern somehow allowed, and this asserts the result is still
        # inside the root. Two cheap checks guarding an arbitrary-write bug.
        if not path.is_relative_to(self.root):
            raise StorageError(f"Key escapes the storage root: {key!r}")
        return path

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRef:
        if len(data) > MAX_OBJECT_BYTES:
            raise StorageError(f"Object is {len(data)} bytes, over the {MAX_OBJECT_BYTES} limit.")
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write to a temporary file in the same directory, then rename.
            # `os.replace` is atomic within a filesystem, so a crash mid-write
            # leaves either the old object or the new one, never half of one.
            temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)

        await asyncio.to_thread(_write)
        return ArtifactRef(
            key=key,
            size_bytes=len(data),
            content_type=content_type or guess_content_type(key),
            url=f"{self.url_prefix}/{key}",
            created_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)

        def _read() -> bytes | None:
            try:
                return path.read_bytes()
            except FileNotFoundError:
                return None

        return await asyncio.to_thread(_read)

    async def delete(self, key: str) -> bool:
        path = self._path(key)

        def _remove() -> bool:
            try:
                path.unlink()
                return True
            except FileNotFoundError:
                return False

        return await asyncio.to_thread(_remove)

    async def exists(self, key: str) -> bool:
        return await asyncio.to_thread(self._path(key).is_file)

    async def healthcheck(self) -> tuple[bool, str]:
        def _check() -> tuple[bool, str]:
            if not self.root.is_dir():
                return False, f"storage root {self.root} does not exist"
            usage = shutil.disk_usage(self.root)
            free_mb = usage.free // (1024 * 1024)
            if free_mb < 50:
                return False, f"only {free_mb}MB free at {self.root}"
            return True, f"local storage at {self.root} ({free_mb}MB free)"

        return await asyncio.to_thread(_check)


class BlobStorage:
    """Azure Blob, against Azurite locally.

    WHY THE SDK IS IMPORTED LAZILY: ``azure-storage-blob`` is an optional
    extra. The default install stays free of it, so someone running the
    zero-setup path never downloads a cloud SDK to play a game that, for them,
    writes to a directory.

    The async SDK is used rather than the sync one wrapped in a thread: this is
    called from request handlers, and a blocking client in an async handler is
    the exact bug the Debugging Dungeon teaches.
    """

    name = "blob"

    def __init__(
        self,
        connection_string: str,
        container: str = "artifacts",
        url_prefix: str = "/api/v1/artifacts",
    ) -> None:
        self.connection_string = connection_string
        self.container = container
        self.url_prefix = url_prefix.rstrip("/")
        self._ensured = False
        self._lock = asyncio.Lock()

    def _client(self):
        try:
            from azure.storage.blob.aio import BlobServiceClient
        except ImportError as exc:  # pragma: no cover - depends on the extra
            raise StorageError(
                "STORAGE_BACKEND=blob needs the azure extra: pip install -e '.[azure]'"
            ) from exc
        return BlobServiceClient.from_connection_string(self.connection_string)

    async def _ensure_container(self) -> None:
        # Created once per process, under a lock so concurrent first requests
        # do not race into a duplicate-create error that looks like an outage.
        if self._ensured:
            return
        async with self._lock:
            if self._ensured:
                return
            from azure.core.exceptions import ResourceExistsError

            async with self._client() as service:
                try:
                    await service.create_container(self.container)
                    log.info("storage.container_created", container=self.container)
                except ResourceExistsError:
                    pass
            self._ensured = True

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRef:
        if len(data) > MAX_OBJECT_BYTES:
            raise StorageError(f"Object is {len(data)} bytes, over the {MAX_OBJECT_BYTES} limit.")
        validate_key(key)
        await self._ensure_container()
        resolved_type = content_type or guess_content_type(key)

        from azure.storage.blob import ContentSettings

        async with self._client() as service:
            blob = service.get_blob_client(self.container, key)
            await blob.upload_blob(
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=resolved_type),
                metadata=metadata or {},
            )
        return ArtifactRef(
            key=key,
            size_bytes=len(data),
            content_type=resolved_type,
            # Deliberately the API's own path, not the blob URL. The browser
            # never learns the container name, and swapping backends changes
            # nothing the frontend can see.
            url=f"{self.url_prefix}/{key}",
            created_at=datetime.now(UTC),
            metadata=dict(metadata or {}),
        )

    async def get(self, key: str) -> bytes | None:
        validate_key(key)
        from azure.core.exceptions import ResourceNotFoundError

        async with self._client() as service:
            blob = service.get_blob_client(self.container, key)
            try:
                stream = await blob.download_blob()
                return await stream.readall()
            except ResourceNotFoundError:
                return None

    async def delete(self, key: str) -> bool:
        validate_key(key)
        from azure.core.exceptions import ResourceNotFoundError

        async with self._client() as service:
            blob = service.get_blob_client(self.container, key)
            try:
                await blob.delete_blob()
                return True
            except ResourceNotFoundError:
                return False

    async def exists(self, key: str) -> bool:
        validate_key(key)
        async with self._client() as service:
            blob = service.get_blob_client(self.container, key)
            return await blob.exists()

    async def healthcheck(self) -> tuple[bool, str]:
        try:
            await self._ensure_container()
            return True, f"blob storage, container {self.container!r}"
        except Exception as exc:
            return False, f"blob storage unreachable: {type(exc).__name__}: {exc}"
