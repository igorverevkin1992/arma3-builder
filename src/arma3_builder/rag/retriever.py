"""High-level retriever combining store search with metadata filters."""
from __future__ import annotations

from dataclasses import dataclass

from .store import Document, ScoredDocument, VectorStore, get_store


@dataclass
class RetrievalHit:
    text: str
    metadata: dict
    score: float


class HybridRetriever:
    """Convenience facade over the configured VectorStore.

    Provides three high-level lookups used by the agents:
      * `commands(query)`     — Biki SQF command pages
      * `classnames(filter)`  — mod classname index with type/faction filters
      * `cba_macros(query)`   — CBA / ACE macros and helpers
    """

    def __init__(self, store: VectorStore | None = None) -> None:
        self.store = store or get_store()

    def upsert(self, docs: list[Document]) -> None:
        self.store.upsert(docs)

    def commands(self, query: str, *, k: int = 5) -> list[RetrievalHit]:
        return self._search(query, k=k, source="biki")

    def cba_macros(self, query: str, *, k: int = 5) -> list[RetrievalHit]:
        return self._search(query, k=k, source="cba")

    def classnames(
        self,
        query: str,
        *,
        k: int = 10,
        type: str | None = None,
        faction: str | None = None,
        side: str | None = None,
        tenants: list[str] | None = None,
    ) -> list[RetrievalHit]:
        flt: dict = {"source": "classnames"}
        if type:
            flt["type"] = type
        if faction:
            flt["faction"] = faction
        if side:
            flt["side"] = side
        if tenants:
            flt["tenant"] = tenants
        return self._raw(query, k=k, metadata_filter=flt)

    # -------------------------------------------------------------- internal

    def _search(self, query: str, *, k: int, source: str) -> list[RetrievalHit]:
        return self._raw(query, k=k, metadata_filter={"source": source})

    def _raw(self, query: str, *, k: int, metadata_filter: dict) -> list[RetrievalHit]:
        results: list[ScoredDocument] = self.store.search(
            query, k=k, metadata_filter=metadata_filter
        )
        return [
            RetrievalHit(text=r.document.text, metadata=r.document.metadata, score=r.score)
            for r in results
        ]
