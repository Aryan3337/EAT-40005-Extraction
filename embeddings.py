#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Semantic retrieval layer - embeddings for the knowledge graph's triples.

Adds a second ranking signal alongside rag.py's keyword scorer. The two are
fused with Reciprocal Rank Fusion (see rag.reciprocal_rank_fusion), so a
question gets the union of what each ranker is good at: keyword matching
still wins on exact graph identifiers like "GaroCommunity", and semantic
matching covers paraphrases keyword lists can never enumerate ("how many
people" vs "population", "reside" vs "live", "beliefs" vs "religion").
"""

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from llm_endpoint import ollama_tunnel_headers, resolve_llm_endpoint

EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")
EMBEDDING_CACHE_DIR = Path(os.getenv("EMBEDDING_CACHE_DIR", "data/embeddings"))
EMBEDDING_TIMEOUT_SECONDS = 30
SEMANTIC_CANDIDATE_LIMIT = 50
MIN_SEMANTIC_SIMILARITY = 0.5


def _embeddings_url() -> str:
    """The Ollama embeddings endpoint, derived from OLLAMA_URL."""
    generate_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    if generate_url.endswith("/api/generate"):
        return generate_url[: -len("/api/generate")] + "/api/embeddings"
    return generate_url


def embed_text(text: str) -> Optional[List[float]]:
    """Embed one string via Ollama. Returns None on any failure."""
    url = resolve_llm_endpoint(_embeddings_url())
    try:
        response = requests.post(
            url,
            json={"model": EMBEDDING_MODEL, "prompt": text},
            headers=ollama_tunnel_headers(),
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        vector = response.json().get("embedding")
        if not isinstance(vector, list) or not vector:
            print(f"Embedding response was empty or malformed for: {text[:60]!r}")
            return None
        return [float(x) for x in vector]
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        print(f"Embedding error: {error}")
        return None


def triple_text(triple: Dict[str, Any]) -> str:
    """The string embedded for one triple: structured triple + sentence_ref."""
    subject = str(triple.get("subject") or "").strip()
    predicate = str(triple.get("predicate") or "").replace("_", " ").lower().strip()
    obj = str(triple.get("object") or "").strip()
    sentence = str(triple.get("sentence_ref") or "").strip()

    base = " ".join(part for part in (subject, predicate, obj) if part)
    if sentence:
        return f"{base}. {sentence}"
    return base


def _norm(vector: List[float]) -> float:
    return math.sqrt(sum(x * x for x in vector))


def _normalize(vector: List[float]) -> List[float]:
    norm = _norm(vector)
    if norm == 0:
        return list(vector)
    return [x / norm for x in vector]


class TripleEmbeddingIndex:
    """In-memory, disk-cached embedding index for a list of triples."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else EMBEDDING_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.vectors: List[List[float]] = []
        self.hashes: List[str] = []
        self.dim: int = 0

    def _cache_path(self) -> Path:
        slug = EMBEDDING_MODEL.replace(":", "_").replace("/", "_")
        return self.cache_dir / f"triple_embeddings_{slug}.json"

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def build_or_load(self, triples: List[Dict[str, Any]], force: bool = False) -> None:
        """Embed every triple, reusing cached vectors for unchanged rows."""
        texts = [triple_text(t) for t in triples]
        hashes = [self._hash(t) for t in texts]

        cached: Dict[str, List[float]] = {}
        if not force and self._cache_path().exists():
            try:
                with open(self._cache_path(), encoding="utf-8") as f:
                    raw = json.load(f)
                if raw.get("model") == EMBEDDING_MODEL:
                    cached = dict(zip(raw.get("hashes", []), raw.get("vectors", [])))
                    print(f"Loaded {len(cached)} cached triple embeddings ({EMBEDDING_MODEL})")
                else:
                    print("Embedding cache is for a different model; rebuilding.")
            except (json.JSONDecodeError, KeyError, OSError) as error:
                print(f"Embedding cache unreadable, rebuilding: {error}")

        vectors: List[Optional[List[float]]] = [None] * len(texts)
        missing: List[Tuple[int, str]] = []
        for i, (h, text) in enumerate(zip(hashes, texts)):
            if h in cached:
                vectors[i] = cached[h]
            else:
                missing.append((i, text))

        if missing:
            print(f"Embedding {len(missing)} new/changed triples with {EMBEDDING_MODEL}...")
            for i, text in missing:
                vec = embed_text(text)
                if vec is None:
                    raise RuntimeError(f"Failed to embed triple at index {i}: {text[:80]!r}")
                vectors[i] = vec

        if any(v is None for v in vectors):
            raise RuntimeError("Embedding index incomplete after build.")

        self.vectors = [_normalize(v) for v in vectors]  # type: ignore[arg-type]
        self.hashes = hashes
        self.dim = len(self.vectors[0]) if self.vectors else 0

        with open(self._cache_path(), "w", encoding="utf-8") as f:
            json.dump({
                "model": EMBEDDING_MODEL,
                "dim": self.dim,
                "hashes": hashes,
                "vectors": self.vectors,
            }, f)
        print(f"Triple embedding index ready: {len(self.vectors)} vectors, dim={self.dim}")

    def semantic_ranking(
        self,
        question: str,
        limit: int = SEMANTIC_CANDIDATE_LIMIT,
        min_similarity: float = MIN_SEMANTIC_SIMILARITY,
    ) -> List[int]:
        """Triple indices ordered best-first by cosine similarity."""
        if not self.vectors:
            return []

        question_vector = embed_text(question)
        if question_vector is None:
            return []

        qnorm = _norm(question_vector)
        if qnorm == 0:
            return []
        qn = [x / qnorm for x in question_vector]

        scored: List[Tuple[float, int]] = []
        for i, vector in enumerate(self.vectors):
            similarity = sum(a * b for a, b in zip(qn, vector))
            if similarity >= min_similarity:
                scored.append((similarity, i))

        scored.sort(key=lambda pair: -pair[0])
        return [i for _, i in scored[:limit]]
