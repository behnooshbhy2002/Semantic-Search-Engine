# Evaluation metrics: Precision@k, Recall@k, MRR.
# Pass a list of labelled test cases to evaluate() to benchmark the pipeline.

import numpy as np


def precision_at_k(relevant_ids: set, results: list, k: int) -> float:
    """
    Fraction of the top-k results that are relevant.

    Example: 3 relevant docs in top-5 → P@5 = 0.6
    """
    top_ids = [d["id"] for d, _ in results[:k]]
    return sum(1 for i in top_ids if i in relevant_ids) / k


def recall_at_k(relevant_ids: set, results: list, k: int) -> float:
    """
    Fraction of all relevant documents that appear in the top-k results.

    Example: 5 relevant docs exist, 3 appear in top-10 → R@10 = 0.6
    """
    top_ids = [d["id"] for d, _ in results[:k]]
    hits    = sum(1 for i in top_ids if i in relevant_ids)
    return hits / len(relevant_ids) if relevant_ids else 0.0


def mrr(relevant_ids: set, results: list) -> float:
    """
    Mean Reciprocal Rank: reciprocal of the rank of the first relevant result.

    Example: first relevant doc is at rank 2 → MRR = 0.5
    """
    for rank, (doc, _) in enumerate(results, 1):
        if doc["id"] in relevant_ids:
            return 1.0 / rank
    return 0.0


def evaluate(engine, test_cases: list, k_precision: int = 5, k_recall: int = 10) -> dict:
    """
    Run the search engine against a labelled test set and report averaged metrics.

    Args:
        engine       — SearchEngine instance
        test_cases   — list of dicts with keys 'query' and 'relevant_ids' (set of int)
        k_precision  — k for Precision@k
        k_recall     — k for Recall@k

    Returns:
        Summary dict: {f'P@{k}': float, f'R@{k}': float, 'MRR': float}

    Example:
        test_cases = [
            {"query": "پردازش تصویر",         "relevant_ids": {2, 27, 93}},
            {"query": "پایان‌نامه دکتری 1402", "relevant_ids": {10, 45}},
        ]
        evaluate(engine, test_cases)
    """
    p_list, r_list, mrr_list = [], [], []

    for tc in test_cases:
        print(f"\n  Query: {tc['query']}")
        results, _ = engine.search(tc["query"], verbose=False)
        rel     = set(tc["relevant_ids"])

        p = precision_at_k(rel, results, k_precision)
        r = recall_at_k(rel, results, k_recall)
        m = mrr(rel, results)

        print(f"  P@{k_precision}={p:.3f}  R@{k_recall}={r:.3f}  MRR={m:.3f}")
        p_list.append(p)
        r_list.append(r)
        mrr_list.append(m)

    summary = {
        f"P@{k_precision}": round(float(np.mean(p_list)), 3),
        f"R@{k_recall}":    round(float(np.mean(r_list)), 3),
        "MRR":              round(float(np.mean(mrr_list)), 3),
    }
    print("\nEvaluation summary:")
    for metric, val in summary.items():
        print(f"  {metric:8s} = {val:.3f}")
    return summary