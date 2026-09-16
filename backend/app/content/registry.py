"""Content pack registry.

Adding a pack is one import and one list entry. Order matters only for the
knowledge graph: a pack whose concepts are prerequisites of another should be
listed first so edges resolve on the first seed pass rather than the second.
"""

from __future__ import annotations

from functools import lru_cache

from app.content.packs import corpus, meta, python_core
from app.content.schema import ContentPack

#: Ordered registry. Foundations first.
_PACK_MODULES = (
    python_core,
    corpus,
    meta,
)


@lru_cache(maxsize=1)
def all_packs() -> tuple[ContentPack, ...]:
    return tuple(module.PACK for module in _PACK_MODULES)


def pack_names() -> list[str]:
    return [p.name for p in all_packs()]


def get_pack(name: str) -> ContentPack | None:
    return next((p for p in all_packs() if p.name == name), None)
