"""Phase 4.5 — Deterministic Semantic Index.

Uses local TF-IDF-style scoring with cosine similarity over token
frequency vectors. No external databases, no embeddings, no network calls.

Algorithm:
- Tokenize text by splitting on non-alphanumeric chars + lowercase.
- Maintain per-token document frequency (DF) across all indexed items.
- At search time: build TF vectors for query and each candidate,
  weight each token by inverse document frequency (IDF = log(N/DF+1)),
  compute cosine similarity.
- Always deterministic: same inputs → same ranked output.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


class SemanticIndex:
    """Local TF-IDF semantic index for deterministic similarity search."""

    def __init__(self) -> None:
        # item_id → { token: raw_count }
        self._token_vectors: dict[str, Counter] = {}
        # item_id → original metadata dict
        self._metadata: dict[str, dict[str, Any]] = {}
        # token → number of documents containing that token
        self._doc_freq: Counter = Counter()

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index(self, item_id: str, text: str, metadata: dict[str, Any] | None = None) -> None:
        """Index or re-index an item."""
        tokens = _tokenize(text)
        if not tokens:
            return

        # If re-indexing, remove old DF contributions first
        if item_id in self._token_vectors:
            self._remove_from_df(item_id)

        tf = Counter(tokens)
        self._token_vectors[item_id] = tf
        self._metadata[item_id] = metadata or {}

        # Update document frequencies
        for token in tf:
            self._doc_freq[token] += 1

    def remove(self, item_id: str) -> None:
        """Remove an item from the index."""
        if item_id in self._token_vectors:
            self._remove_from_df(item_id)
            del self._token_vectors[item_id]
            del self._metadata[item_id]

    def _remove_from_df(self, item_id: str) -> None:
        for token in self._token_vectors[item_id]:
            self._doc_freq[token] -= 1
            if self._doc_freq[token] <= 0:
                del self._doc_freq[token]

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        top_k: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[tuple[str, float, list[str]]]:
        """Search the index and return (item_id, score, matched_tokens) tuples.

        Results are sorted descending by score, then ascending by item_id for
        determinism when scores are equal.
        """
        query_tokens = _tokenize(query)
        if not query_tokens or not self._token_vectors:
            return []

        n_docs = len(self._token_vectors)
        query_tf = Counter(query_tokens)

        # Build IDF-weighted query vector
        query_vec = self._idf_vector(query_tf, n_docs)
        query_norm = _vec_norm(query_vec)

        if query_norm == 0.0:
            return []

        results: list[tuple[str, float, list[str]]] = []

        for item_id, item_tf in self._token_vectors.items():
            # Apply metadata filters
            if filters:
                meta = self._metadata.get(item_id, {})
                if not all(meta.get(k) == v for k, v in filters.items()):
                    continue

            item_vec = self._idf_vector(item_tf, n_docs)
            item_norm = _vec_norm(item_vec)
            if item_norm == 0.0:
                continue

            # Cosine similarity
            dot = sum(query_vec.get(t, 0.0) * item_vec.get(t, 0.0) for t in query_vec)
            score = dot / (query_norm * item_norm)

            if score > 0.0:
                # Track which query tokens matched
                matched = [t for t in query_tf if t in item_tf]
                results.append((item_id, round(score, 6), matched))

        results.sort(key=lambda x: (-x[1], x[0]))
        return results[:top_k]

    def _idf_vector(self, tf: Counter, n_docs: int) -> dict[str, float]:
        """Produce an IDF-weighted vector from a raw term-frequency counter."""
        vec: dict[str, float] = {}
        for token, count in tf.items():
            df = self._doc_freq.get(token, 0)
            # Smoothed IDF: log((N+1)/(df+1)) + 1
            idf = math.log((n_docs + 1) / (df + 1)) + 1.0
            vec[token] = count * idf
        return vec

    def __len__(self) -> int:
        return len(self._token_vectors)


def _vec_norm(vec: dict[str, float]) -> float:
    return math.sqrt(sum(v * v for v in vec.values()))
