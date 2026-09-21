"""The storage contract, and the parts both backends share.

The protocol is deliberately small. Five operations cover every use the game
has, and each extra one would be a method two backends must keep in step — so
there is no `list_by_prefix`, no `copy`, no signed-upload-URL, because nothing
needs them yet.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


class StorageError(RuntimeError):
    """Storage failed. Distinct from a missing object, which returns ``None``.

    The distinction matters at the call site: a missing figure is a normal
    outcome worth rendering as "no chart", while a storage outage is an incident
    worth logging loudly.
    """


#: Content types the game actually produces. An allow-list rather than a
#: blocklist: this storage serves bytes back to a browser, so a permissive
#: mapping is how a submitted "figure" becomes stored HTML and then stored XSS.
ALLOWED_CONTENT_TYPES: dict[str, str] = {
    "png": "image/png",
    "svg": "image/svg+xml",
    "json": "application/json",
    "txt": "text/plain; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}

#: Keys are paths in a bucket. Constrain them hard: a key is built from user
#: input (a challenge slug, a player id) and a `..` in the wrong place turns
#: the local backend into an arbitrary-write primitive.
_SAFE_KEY = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,200}$")


def validate_key(key: str) -> str:
    """Reject anything that is not a plain, relative, traversal-free path."""
    if not _SAFE_KEY.match(key):
        raise StorageError(f"Unsafe storage key: {key!r}")
    # Checked separately from the pattern so the error says which rule broke.
    if ".." in key or key.startswith("/") or "//" in key:
        raise StorageError(f"Unsafe storage key: {key!r}")
    return key


def guess_content_type(key: str) -> str:
    extension = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    return ALLOWED_CONTENT_TYPES.get(extension, "application/octet-stream")


def content_hash(data: bytes) -> str:
    """Short, stable digest used to build content-addressed keys.

    Content addressing means re-submitting identical code that produces an
    identical figure overwrites the same object rather than accumulating a new
    one per attempt — and attempts are the thing this game generates most of.
    """
    return hashlib.blake2b(data, digest_size=10).hexdigest()


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """What a caller gets back after storing something.

    ``url`` is what the frontend renders. It is a path served by the API rather
    than a direct storage URL, so the local and blob backends look identical to
    the browser and neither leaks a container name or a SAS token into markup.
    """

    key: str
    size_bytes: int
    content_type: str
    url: str
    created_at: datetime
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
            "url": self.url,
            "created_at": self.created_at.isoformat(),
            "metadata": dict(self.metadata),
        }


@runtime_checkable
class ObjectStorage(Protocol):
    """Five operations. Both backends implement exactly these."""

    name: str

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ArtifactRef: ...

    async def get(self, key: str) -> bytes | None:
        """Bytes, or ``None`` when the object does not exist."""
        ...

    async def delete(self, key: str) -> bool:
        """``True`` if something was removed, ``False`` if it was already gone."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def healthcheck(self) -> tuple[bool, str]: ...
