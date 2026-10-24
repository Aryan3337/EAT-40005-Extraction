#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Semantic retrieval layer – embeddings for the knowledge graph's triples.

Adds a second ranking signal alongside rag.py's keyword scorer. The two are
fused with Reciprocal Rank Fusion (see rag.reciprocal_rank_fusion), so a
question gets the union of what each ranker is good at: keyword matching
still wins on exact graph identifiers like "GaroCommunity", and semantic
matching covers the paraphrases keyword lists can never enumerate ("how
many people" vs "population", "reside" vs "live", "beliefs" vs "religion").

Design choices, all deliberate:
    - nomic-embed-text via Ollama, not a hosted embedding API. The project
      already committed that paper content goes to a local model only, and
      sentence_ref is verbatim paper text. resolve_llm_endpoint enforces it.
    - Pure Python, no numpy. At 45-350 triples and 768 dims a query is
      ~270k multiply-adds, single-digit milliseconds. Adding numpy for that
      is a dependency cost this project does not need to pay yet.
    - Disk-cached by content hash. Regenerating the CSV or ingesting a new
      paper only re-embeds the rows whose text actually changed; unchanged
      rows are loaded from cache. Verified via the stored hash list.
    - Per-triple text combines the structured triple AND sentence_ref, so
      the model sees both the relationship and its surrounding context.
"""

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from llm_endpoint import ollama_tunnel_headers, resolve_llm_endpoint

# 137M params, 768 dims, ~15-40 ms per short query on this machine's CPU.
# all-minilm (46 MB, 384 dims) is faster but weaker on the relational,
# named-entity-heavy text this graph stores. Overridable so switching is
# one env var and one cache rebuild, not a code change.
EMBEDDING_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

# Vectors are cached here; the directory is created on first use. Keyed by
# model name so switching models does not serve stale vectors.
EMBEDDING_CACHE_DIR = Path(os.getenv("EMBEDDING_CACHE_DIR", "data/embeddings"))

# Generous: embedding a single short text on this CPU is well under a
# second, and a cold model load is a few seconds. Failing here just falls
# back to keyword-only retrieval, which is the pre-existing behaviour.
EMBEDDING_TIMEOUT_SECONDS = 30

# How many top-of-semantic-ranking triples to feed into RRF. Cosine
# similarity is never exactly 0 for real text, so without a cap every
# triple would appear in the fused result and keyword rankings would be
# diluted by semantically-distant noise. 50 is comfortably above
# DEFAULT_TOP_K=25 and above the ~350-triple graph's useful neighbourhood.
SEMANTIC_CANDIDATE_LIMIT = 50

# Optional similarity floor. 0.0 keeps every ranked candidate, which is
# correct when RRF is doing the filtering (low-similarity triples get low
# RRF scores and do not survive top_k). Raise this only after measuring
# real similarity distributions from your own embedding model -- a value
# that looks reasonable for one model silently drops evidence for another.
MIN_SEMANTIC_SIMILARITY = 0.0


def _embeddings_url() -> str:
    """The Ollama embeddings endpoint, derived from the same OLLAMA_URL the
    rest of the project already configures.

    Uses /api/embed (plural, `input` field), NOT /api/embeddings (singular,
    `prompt` field). Ollama deprecated the singular route and recent
    versions return 404 for it, which is what caused the silent
    'Semantic index unavailable' fallback this project hit on 2026-10-14.
    """
    generate_url = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
    if generate_url.endswith("/api/generate"):
        return generate_url[: -len("/api/generate")] + "/api/embed"
    if generate_url.endswith("/api/embeddings"):
        return generate_url[: -len("/api/embeddings")] + "/api/embed"
    return generate_url


def embed_text(text: str) -> Optional[List[float]]:
    """Embed one string via Ollama.

    Handles both response shapes:
      - /api/embed  -> {"embeddings": [[...]]}   (current)
      - /api/embeddings -> {"embedding": [...]}  (deprecated, kept as a
        fallback for older Ollama installs so this does not break for
        anyone who has not upgraded yet)
    """
    url = resolve_llm_endpoint(_embeddings_url())
    try:
        response = requests.post(
            url,
            json={"model": EMBEDDING_MODEL, "input": text},
            headers=ollama_tunnel_headers(),
            timeout=EMBEDDING_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        body = response.json()

        # Current shape: {"embeddings": [[...]]} -- a batch response, so
        # take the first (and only) vector.
        vectors = body.get("embeddings")
        if isinstance(vectors, list) and vectors and isinstance(vectors[0], list):
            return [float(x) for x in vectors[0]]

        # Deprecated shape: {"embedding": [...]}
        vector = body.get("embedding")
        if isinstance(vector, list) and vector:
            return [float(x) for x in vector]

        print(f"Embedding response was empty or malformed for: {text[:60]!r}")
        return None
    except (requests.RequestException, ValueError, KeyError, TypeError) as error:
        print(f"Embedding error: {error}")
        return None


def triple_text(triple: Dict[str, Any]) -> str:
    """The string embedded for one triple.

    Combines the structured triple (so the model sees the relationship) with
    the source sentence (so it sees the surrounding context). The predicate
    is lowercased with underscores expanded -- "LIVING_IN" reads as "living
    in", which is what a general-purpose embedding model was trained on,
    whereas the raw uppercase graph label is not.
    """
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
    """In-memory, disk-cached embedding index for a list of triples.

    Sized for this project (45 triples today, ~350 after 20 papers). At 768
    dims a full index is well under a megabyte of JSON, so a dedicated
    vector database would be heavier than the data it stores.
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else EMBEDDING_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.vectors: List[List[float]] = []   # L2-normalized, one per triple
        self.hashes: List[str] = []
        self.dim: int = 0

    def _cache_path(self) -> Path:
        slug = EMBEDDING_MODEL.replace(":", "_").replace("/", "_")
        return self.cache_dir / f"triple_embeddings_{slug}.json"

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]

    def build_or_load(self, triples: List[Dict[str, Any]], force: bool = False) -> None:
        """Embed every triple, reusing cached vectors for unchanged rows.

        Raises RuntimeError if any embedding call fails -- an unembedded
        triple would be invisible to the semantic ranker, which is exactly
        the silent-miss failure mode this project's comments repeatedly
        warn against. RAGSkeleton catches that and disables semantic
        retrieval rather than serving partial results.
        """
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
                    print(f"Embedding cache is for a different model; rebuilding.")
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
                    raise RuntimeError(
                        f"Failed to embed triple at index {i}: {text[:80]!r}"
                    )
                vectors[i] = vec

        if any(v is None for v in vectors):
            raise RuntimeError("Embedding index incomplete after build.")

        # Normalize once, here, so semantic_ranking only normalizes the
        # question at query time rather than every stored vector.
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
        """Triple indices ordered best-first by cosine similarity to the
        question. Returns [] when embeddings are unavailable, so callers
        fuse an empty ranking rather than fail."""
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
            # Stored vectors are already normalized, so this dot product is
            # the cosine similarity directly.
            similarity = sum(a * b for a, b in zip(qn, vector))
            if similarity >= min_similarity:
                scored.append((similarity, i))

        scored.sort(key=lambda pair: -pair[0])
        return [i for _, i in scored[:limit]]