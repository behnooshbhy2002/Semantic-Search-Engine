from __future__ import annotations

import re

import faiss
import numpy as np


# ── Text utilities ────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[\u0600-\u06FF\w]+")


def _tokenise(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def _ngram_candidates(tokens: list[str], max_n: int = 2) -> list[str]:
    """Return unique 1-gram … max_n-gram candidates from *tokens*."""
    seen, out = set(), []
    for n in range(1, max_n + 1):
        for i in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[i : i + n])
            if phrase not in seen:
                seen.add(phrase)
                out.append(phrase)
    return out


# ── Embedding helpers ─────────────────────────────────────────────────────────

def _embed(bi_encoder, texts: list[str]) -> np.ndarray:
    """Encode *texts* with the E5-style query prefix and L2-normalise."""
    vecs = bi_encoder.encode(
        ["query: " + t for t in texts],
        convert_to_numpy=True,
        show_progress_bar=False,
        batch_size=32,
    ).astype("float32")
    faiss.normalize_L2(vecs)
    return vecs


def _cosine_scores(query_vec: np.ndarray, candidate_vecs: np.ndarray) -> np.ndarray:
    """Cosine similarity between one query vector and many candidate vectors."""
    return (candidate_vecs @ query_vec.T).flatten()


# ── Source 2 & 3: embedding-based + KeyBERT-style ────────────────────────────

def _embedding_expansion(
    query:         str,
    bi_encoder,
    top_n:         int   = 4,
    sim_threshold: float = 0.70,
) -> list[str]:

    tokens = _tokenise(query)
    if len(tokens) < 2:
        return []

    candidates = _ngram_candidates(tokens, max_n=2)
    if not candidates:
        return []

    all_texts  = [query] + candidates
    embeddings = _embed(bi_encoder, all_texts)

    query_vec      = embeddings[0:1]
    candidate_vecs = embeddings[1:]
    scores         = _cosine_scores(query_vec, candidate_vecs)

    # Source 2: all candidates above threshold (excluding exact match with query)
    above_threshold = [
        candidates[i]
        for i in range(len(candidates))
        if scores[i] >= sim_threshold and candidates[i] != query
    ]

    # Source 3: top_n by score (KeyBERT-style)
    top_indices = np.argsort(scores)[::-1][:top_n]
    keybert     = [candidates[i] for i in top_indices if candidates[i] != query]

    # Merge: threshold-based first, then KeyBERT additions
    seen, merged = set(), []
    for phrase in above_threshold + keybert:
        if phrase not in seen:
            seen.add(phrase)
            merged.append(phrase)

    return merged


# ── Public API ────────────────────────────────────────────────────────────────

def expand(
    query:              str,
    bi_encoder,
    llm_expansions:     list[str] | None = None,
    max_additions:      int               = 8,
    sim_threshold:      float             = 0.70,
    keybert_top_n:      int               = 4,
) -> str:

    if not query or not query.strip():
        return query

    original_tokens = set(_tokenise(query))
    additions: list[str] = []
    seen: set[str]        = set(original_tokens)

    def _add(terms: list[str]) -> None:
        for term in terms:
            term = term.strip()
            if term and term not in seen:
                additions.append(term)
                seen.add(term)

    # Source 1: LLM expanded_keywords
    _add(llm_expansions or [])

    # Source 2 + 3: embedding-based + KeyBERT (only if query has enough tokens)
    embedding_terms = _embedding_expansion(
        query, bi_encoder,
        top_n=keybert_top_n,
        sim_threshold=sim_threshold,
    )
    _add(embedding_terms)

    if not additions:
        return query

    extra = " ".join(additions[:max_additions])
    return f"{query} {extra}".strip()