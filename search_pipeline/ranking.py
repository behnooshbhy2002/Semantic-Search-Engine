# Ranking utilities: BM25 scoring and Reciprocal Rank Fusion (RRF).

import numpy as np

try:
    from rank_bm25 import BM25Okapi
    HAS_BM25 = True
except ImportError:
    HAS_BM25 = False
    print("⚠️  rank_bm25 not installed — pip install rank_bm25")


def bm25_score(query: str, texts: list[str]) -> np.ndarray:
    """
    Score each text against the query using BM25Okapi.

    BM25 is a classic lexical retrieval model that rewards
    term frequency while penalising very long documents.
    Returns a zero array if rank_bm25 is not installed.
    """
    if not HAS_BM25 or not texts:
        return np.zeros(len(texts))

    tokenized = [t.split() for t in texts]
    bm25      = BM25Okapi(tokenized)
    return bm25.get_scores(query.split())


def reciprocal_rank_fusion(rank_lists: list[list], k: int = 60) -> dict:
    """
    Merge multiple ranked lists into a single score dict using RRF.

    Formula: score(d) = Σ  1 / (k + rank(d))
    A document that appears near the top of several lists accumulates
    a higher combined score than one that tops only a single list.

    Args:
        rank_lists: list of doc-id lists, each sorted best-first
        k:          smoothing constant (typically 60)

    Returns:
        {doc_id: rrf_score} — higher is better
    """
    scores: dict = {}
    for ranked_list in rank_lists:
        for rank, doc_id in enumerate(ranked_list):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores