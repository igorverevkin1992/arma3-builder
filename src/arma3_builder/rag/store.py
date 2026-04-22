"""Vector store backends.

Two implementations:
  * MemoryStore — pure-python BM25 + tiny hashed embedding (offline / tests)
  * QdrantStore — production backend with metadata filters

Both expose the same interface so the retriever can swap without code changes.
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Iterable, Protocol

from ..config import get_settings


@dataclass
class Document:
    id: str
    text: str
    metadata: dict
    embedding: list[float] | None = None


@dataclass
class ScoredDocument:
    document: Document
    score: float


class VectorStore(Protocol):
    def upsert(self, docs: Iterable[Document]) -> None: ...
    def search(
        self,
        query: str,
        *,
        k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[ScoredDocument]: ...
    def count(self) -> int: ...


# --------------------------------------------------------------------------- #
# In-memory implementation (BM25 + hashed embeddings)
# --------------------------------------------------------------------------- #


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _hashed_embed(tokens: list[str], dim: int = 256) -> list[float]:
    vec = [0.0] * dim
    for tok in tokens:
        h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
        vec[h % dim] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


_ST_MODEL = None


def _sentence_transformer_embed(text: str) -> list[float] | None:
    """Optional dense embedding via `sentence-transformers`.

    Loaded lazily and cached. Returns None if the package (or model) is
    unavailable, in which case the caller falls back to the hashed embedding.
    Controlled by env ``ARMA3_ST_MODEL`` (defaults to MiniLM for CPU speed).
    """
    import os
    global _ST_MODEL
    if _ST_MODEL is False:
        return None
    if _ST_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

            model_name = os.environ.get(
                "ARMA3_ST_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
            )
            _ST_MODEL = SentenceTransformer(model_name)
        except Exception:  # noqa: BLE001
            _ST_MODEL = False
            return None
    try:
        vec = _ST_MODEL.encode(text, normalize_embeddings=True)
        return vec.tolist()
    except Exception:  # noqa: BLE001
        return None


@dataclass
class MemoryStore:
    docs: list[Document] = field(default_factory=list)
    _index: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    _doc_lens: list[int] = field(default_factory=list)

    def upsert(self, docs: Iterable[Document]) -> None:
        for d in docs:
            tokens = _tokens(d.text)
            d.embedding = _hashed_embed(tokens)
            doc_id = len(self.docs)
            self.docs.append(d)
            self._doc_lens.append(len(tokens))
            counter = Counter(tokens)
            for tok, cnt in counter.items():
                self._index.setdefault(tok, []).append((doc_id, cnt))

    def count(self) -> int:
        return len(self.docs)

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[ScoredDocument]:
        if not self.docs:
            return []

        q_tokens = _tokens(query)
        q_vec = _hashed_embed(q_tokens)

        n = len(self.docs)
        avgdl = sum(self._doc_lens) / n if n else 0.0
        k1, b = 1.5, 0.75

        scores: dict[int, float] = {}
        for tok in set(q_tokens):
            postings = self._index.get(tok, [])
            df = len(postings)
            if df == 0:
                continue
            idf = math.log((n - df + 0.5) / (df + 0.5) + 1)
            for doc_id, tf in postings:
                dl = self._doc_lens[doc_id] or 1
                denom = tf + k1 * (1 - b + b * dl / (avgdl or 1))
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * (tf * (k1 + 1) / denom)

        # Dense cosine adds a small semantic boost.
        for doc_id, doc in enumerate(self.docs):
            if doc.embedding is None:
                continue
            dot = sum(q * d for q, d in zip(q_vec, doc.embedding))
            scores[doc_id] = scores.get(doc_id, 0.0) + 0.5 * dot

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        out: list[ScoredDocument] = []
        for doc_id, score in ranked:
            doc = self.docs[doc_id]
            if metadata_filter and not _matches(doc.metadata, metadata_filter):
                continue
            out.append(ScoredDocument(document=doc, score=score))
            if len(out) >= k:
                break
        return out


def _matches(meta: dict, flt: dict) -> bool:
    for key, expected in flt.items():
        actual = meta.get(key)
        if isinstance(expected, (list, tuple, set)):
            if actual not in expected:
                return False
        elif actual != expected:
            return False
    return True


# --------------------------------------------------------------------------- #
# Qdrant implementation (lazy import — only loaded when configured)
# --------------------------------------------------------------------------- #


class QdrantStore:
    """Qdrant-backed store with metadata payload filters.

    Uses the in-process hashed embedding so tests don't need an embedding
    model. Production deployments swap in `sentence-transformers` by
    overriding `_embed`.
    """

    def __init__(self, *, collection: str = "arma3_kb", dim: int = 256) -> None:
        try:
            from qdrant_client import QdrantClient  # type: ignore[import-not-found]
            from qdrant_client.http import models  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("qdrant-client not installed") from exc

        s = get_settings()
        self._models = models
        self.client = QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key or None)
        self.collection = collection
        self.dim = dim
        existing = {c.name for c in self.client.get_collections().collections}
        if collection not in existing:
            self.client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE),
            )

    def _embed(self, text: str) -> list[float]:
        dense = _sentence_transformer_embed(text)
        if dense is not None and len(dense) == self.dim:
            return dense
        return _hashed_embed(_tokens(text), dim=self.dim)

    def upsert(self, docs: Iterable[Document]) -> None:
        points = []
        for d in docs:
            vec = d.embedding or self._embed(d.text)
            points.append(
                self._models.PointStruct(
                    id=d.id,
                    vector=vec,
                    payload={"text": d.text, **d.metadata},
                )
            )
        if points:
            self.client.upsert(collection_name=self.collection, points=points)

    def count(self) -> int:
        return self.client.count(collection_name=self.collection, exact=True).count

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        metadata_filter: dict | None = None,
    ) -> list[ScoredDocument]:
        flt = None
        if metadata_filter:
            must = []
            for key, val in metadata_filter.items():
                if isinstance(val, (list, tuple, set)):
                    must.append(self._models.FieldCondition(
                        key=key,
                        match=self._models.MatchAny(any=list(val)),
                    ))
                else:
                    must.append(self._models.FieldCondition(
                        key=key,
                        match=self._models.MatchValue(value=val),
                    ))
            flt = self._models.Filter(must=must)
        results = self.client.search(
            collection_name=self.collection,
            query_vector=self._embed(query),
            query_filter=flt,
            limit=k,
        )
        return [
            ScoredDocument(
                document=Document(
                    id=str(p.id),
                    text=p.payload.get("text", ""),
                    metadata={k: v for k, v in p.payload.items() if k != "text"},
                ),
                score=p.score,
            )
            for p in results
        ]


def get_store() -> VectorStore:
    s = get_settings()
    if s.rag_backend == "qdrant":
        return QdrantStore()
    return MemoryStore()
