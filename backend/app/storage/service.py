"""Backend selection, and the keys the game actually uses.

One process holds one storage instance. It is built lazily on first use rather
than at import, so a misconfigured connection string fails when something tries
to store a figure — not when the test suite imports a module.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.storage.base import ObjectStorage, StorageError, content_hash

log = get_logger(__name__)

_storage: ObjectStorage | None = None


def build_storage(cfg: Settings) -> ObjectStorage:
    from app.storage.backends import BlobStorage, LocalStorage

    if cfg.storage_backend == "blob":
        if not cfg.blob_connection_string:
            # Loud, not a silent downgrade to local. A deployment that believes
            # it is writing to blob and is quietly writing to a container's
            # ephemeral disk loses every artifact on the next restart, and
            # discovers it weeks later.
            raise StorageError("STORAGE_BACKEND=blob requires BLOB_CONNECTION_STRING to be set.")
        return BlobStorage(
            cfg.blob_connection_string,
            container=cfg.blob_container,
            url_prefix=f"{cfg.api_v1_prefix}/artifacts",
        )
    return LocalStorage(
        Path(cfg.local_storage_path),
        url_prefix=f"{cfg.api_v1_prefix}/artifacts",
    )


def get_storage() -> ObjectStorage:
    global _storage
    if _storage is None:
        _storage = build_storage(get_settings())
        log.info("storage.initialised", backend=_storage.name)
    return _storage


def reset_storage() -> None:
    """Drop the cached instance. For tests that switch backends."""
    global _storage
    _storage = None


# ── Key layout ───────────────────────────────────────────────────────────────
# Keys are content-addressed under a per-player, per-challenge prefix:
#
#     figures/<profile>/<challenge>/<hash>.png
#
# Three properties fall out of that shape. Re-running the same code overwrites
# rather than accumulating, which matters because attempts are what this game
# produces most of. A player's artifacts are contiguous, so deleting an account
# is a prefix delete. And the hash in the name means a cached URL is never
# stale — different bytes get a different key.


def figure_key(profile_id: str, challenge_slug: str, data: bytes, extension: str = "png") -> str:
    return f"figures/{profile_id}/{challenge_slug}/{content_hash(data)}.{extension}"


def artifact_key(profile_id: str, kind: str, data: bytes, extension: str) -> str:
    return f"{kind}/{profile_id}/{content_hash(data)}.{extension}"
