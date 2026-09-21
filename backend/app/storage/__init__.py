"""Object storage for player artifacts.

WHAT GOES IN HERE, and why it is not the database: matplotlib figures from the
data-visualisation challenges, benchmark traces, and any submission artifact
large enough that putting it in Postgres would mean every query that touches
the row drags a megabyte of binary with it. Small structured data stays in the
database; bytes go here.

WHY THERE IS AN ABSTRACTION AT ALL — the spec is explicit that an abstraction
needs a reason, so here is the reason and not a shrug. There are two backends
that must both be real:

  * ``local``  — a directory on disk. The zero-setup path. ``python -m app.cli
    bootstrap`` with no Docker, no emulator and no connection string has to keep
    working, because that is how someone tries this project for the first time.
  * ``blob``   — Azure Blob, against Azurite locally. What the deployed shape
    would use, and what the DevOps missions get to inspect.

One protocol, two implementations, chosen by config. Without the seam the
choice becomes an ``if`` at every call site, which is where the two paths drift
until only one of them is ever exercised.

WHAT THE SANDBOX DOES NOT GET: credentials. The sandbox has no network and no
secrets by design (ADR-001), so it cannot and must not write here. Figures come
back over the existing execution protocol as bounded base64, and the *game
server* stores them. That asymmetry is the whole point of the boundary, and it
is why ``capture`` lives in the runner while ``put`` lives here.
"""

from __future__ import annotations

from app.storage.base import (
    ArtifactRef,
    ObjectStorage,
    StorageError,
    content_hash,
    guess_content_type,
)
from app.storage.service import get_storage, reset_storage

__all__ = [
    "ArtifactRef",
    "ObjectStorage",
    "StorageError",
    "content_hash",
    "get_storage",
    "guess_content_type",
    "reset_storage",
]
