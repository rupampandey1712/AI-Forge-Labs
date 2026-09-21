"""Serving stored artifacts back to the browser.

WHY THE API SERVES THESE rather than handing out a storage URL: the frontend
must not know or care which backend is configured. A direct blob URL would leak
the container name into markup, would need a SAS token to be private, and would
change shape the moment the backend changes. One path, both backends.

THE SECURITY PROPERTY THIS ROUTE EXISTS TO ENFORCE: keys embed the owning
player's id, so serving a key without checking it against the caller would let
any authenticated player read any other player's artifacts by guessing a path.
That check is the reason this is a route with a dependency rather than a static
file mount.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.api.deps import CurrentProfile
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.storage import get_storage
from app.storage.base import ALLOWED_CONTENT_TYPES, StorageError, guess_content_type

log = get_logger(__name__)

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


@router.get("/{key:path}")
async def get_artifact(
    key: Annotated[
        str, Path(description="Storage key, e.g. figures/<profile>/<challenge>/<hash>.png")
    ],
    profile: CurrentProfile,
) -> Response:
    """Return one stored artifact.

    Ownership is enforced by the key layout: every key produced by this
    application is `<kind>/<profile_id>/...`, so a key whose second segment is
    not the caller's profile is someone else's and is refused. This is checked
    *before* touching storage — a 404 that only appears after a successful read
    still tells the caller the object exists.
    """
    segments = key.split("/")
    if len(segments) < 2 or segments[1] != str(profile.id):
        # Deliberately 404 rather than 403. A 403 confirms the object exists,
        # which turns key-guessing into an enumeration oracle.
        log.warning("artifact.forbidden", key=key[:120], profile_id=str(profile.id))
        raise NotFoundError("Artifact not found.")

    content_type = guess_content_type(key)
    if content_type not in ALLOWED_CONTENT_TYPES.values():
        # The storage layer allow-lists on write; this allow-lists on read too,
        # so an object written before a policy change cannot be served as a
        # type the browser will execute.
        raise NotFoundError("Artifact not found.")

    try:
        data = await get_storage().get(key)
    except StorageError as exc:
        log.error("artifact.read_failed", key=key[:120], error=str(exc)[:200])
        raise NotFoundError("Artifact not found.") from exc

    if data is None:
        raise NotFoundError("Artifact not found.")

    return Response(
        content=data,
        media_type=content_type,
        headers={
            # Content-addressed keys mean the bytes for a given key never
            # change, so this can be cached hard and forever.
            "Cache-Control": "private, max-age=31536000, immutable",
            # It is a PNG from a sandbox, but defence in depth costs one header:
            # no sniffing, no framing, and never executed as a document.
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; img-src 'self'; sandbox",
            "Content-Disposition": "inline",
        },
    )
