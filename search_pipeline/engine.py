# engine.py
# Search engine — orchestrates all pipeline stages.
#
# Two query-parsing strategies (user-selectable per request):
#
#   "llm"  — delegates to llm_parser.extract(); on failure falls back to "rule"
#   "rule" — hand-crafted regex/fuzzy parser in query_parser.py
#
# The semantic_query that reaches the encoders is:
#   • LLM mode  → the `keywords` field returned by the LLM
#   • Rule mode → the original query with filter tokens stripped out
#
# Cross-encoder is a single model selected by the user from the UI dropdown
# and hot-swapped via models.set_cross_encoder().

from __future__ import annotations

import logging
import time

import faiss
import numpy as np

from . import llm_parser
from .config      import DEFAULT_TOP_K, MAX_EXPANSIONS, RRF_K
from .database    import apply_filters, fetch_full_docs
from .expander    import expand
from .normalizer  import normalize
from .query_parser import parse_filters, strip_filter_tokens
from .ranking     import HAS_BM25, bm25_score, reciprocal_rank_fusion
from .display_persain import process_farsi_text

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_texts(rows: list[tuple]) -> list[str]:
    """Concatenate title + abstract + keywords into a single normalised string."""
    return [normalize(f"{r[1] or ''} {r[2] or ''} {r[3] or ''}") for r in rows]


def _rrf_merge(list_a: list[int], list_b: list[int], limit: int) -> list[int]:
    """Merge two ranked ID lists with RRF and return the top *limit* IDs."""
    fused = reciprocal_rank_fusion([list_a, list_b], k=RRF_K)
    return [doc_id for doc_id, _ in sorted(fused.items(), key=lambda x: -x[1])][:limit]


# ── Search engine ─────────────────────────────────────────────────────────────

class SearchEngine:
    """
    Hybrid search engine combining:
      • Dense retrieval  — FAISS inner-product over bi-encoder embeddings
      • Sparse retrieval — BM25 (optional, requires rank_bm25)
      • Reranking        — cross-encoder (model selectable at runtime)

    Two retrieval paths:
      Filtered  — SQL pre-filter narrows the candidate set, then FAISS+BM25 ranks within it.
      Full      — FAISS over the entire index, fused with global BM25.
    """

    def __init__(self, models):
        self.models = models

    # ── Public API ────────────────────────────────────────────────────────────

    def search(
        self,
        query:       str,
        top_k:       int  = DEFAULT_TOP_K,
        use_bm25:    bool = True,
        use_expand:  bool = True,
        use_or:      bool = False,
        parser_mode: str  = "llm",   # "llm" | "rule"
        ce_key:      str  = None,
        verbose:     bool = True,
    ) -> tuple[list[tuple[dict, float]], str, str, bool]:

        t0 = time.time()

        if ce_key:
            self.models.set_cross_encoder(ce_key)

        query = normalize(query)

        filters, semantic_query, parser_used, sql_only, llm_expansions = self._parse(
            query, parser_mode, verbose
        )

        # ── SQL-only path: skip every vector/ML step ──────────────────────────
        or_used = False
        filtered_rows = []
        if filters:
            filtered_rows = apply_filters(filters, "AND")
            if not filtered_rows and use_or:
                print("----- Using OR operator for increasing recall -----")
                filtered_rows = apply_filters(filters, "OR")
                or_used = True

        if sql_only:
            if verbose:
                print("   ⚡ SQL-only mode — skipping bi-encoder / reranker.")
            docs    = fetch_full_docs([r[0] for r in filtered_rows])[:top_k]
            results = [(doc, 0.0) for doc in docs]
            if verbose:
                self._log_results(results, time.time() - t0)
            return results, "", parser_used, or_used

        # ── Hybrid path: FAISS + BM25 + reranker ─────────────────────────────
        if use_expand and semantic_query:
            expanded = expand(
                semantic_query,
                self.models.bi_encoder,
                llm_expansions=llm_expansions,
                max_additions=MAX_EXPANSIONS,
            )
        else:
            expanded = semantic_query
            if verbose:
                print("   ⏭️ Query expansion skipped")

        if verbose:
            self._log_query(query, semantic_query, expanded, filters, parser_used)

        if semantic_query:
            candidate_ids = (
                self._filtered_search(semantic_query, expanded, filtered_rows, top_k, use_bm25, verbose)
                if filtered_rows
                else self._full_search(semantic_query, expanded, top_k, use_bm25)
            )

            docs = fetch_full_docs(candidate_ids)
            if not docs:
                log.info("No candidate documents found.")
                return [], expanded, parser_used
            
            results = self.models.rerank(semantic_query, docs)[:top_k]

            if verbose:
                self._log_results(results, time.time() - t0)

            return results, expanded, parser_used, or_used
        
        if not semantic_query and not filtered_rows:
            return [], [], parser_used, or_used

    # ── Parsing ───────────────────────────────────────────────────────────────

    def _parse(
        self,
        query:       str,
        parser_mode: str,
        verbose:     bool,
    ) -> tuple[dict, str | None, str, bool, list[str] | None]:

        if parser_mode == "llm":
            if verbose:
                print("Trying LLM parser...")
            result = llm_parser.extract(query)

            if result.success:
                has_filters  = bool(result.filters)
                has_keywords = bool(result.keywords)

                if verbose:
                    print(process_farsi_text(f"   LLM filters:    {result.filters}"))
                    print(process_farsi_text(f"   LLM keywords:   {result.keywords or '(none — SQL-only mode)'}"))
                    print(process_farsi_text(f"   LLM expansions: {result.expanded_keywords}"))

                # Filters present but no semantic keywords → pure SQL lookup
                if has_filters and not has_keywords:
                    return result.filters, None, "llm", True, None
                

                return result.filters, result.keywords, "llm", False, result.expanded_keywords

            if verbose:
                print("   LLM failed — falling back to rule parser.")

        # Rule parser (explicit choice or LLM fallback)
        filters        = parse_filters(query)
        semantic_query = strip_filter_tokens(query, filters)

        # Guard: never send an empty string to the encoders
        if len(semantic_query.strip()) < 2:
            semantic_query = None
            return filters, semantic_query, "rule", True, None

        return filters, semantic_query, "rule", False, None

    # ── Retrieval: filtered path ──────────────────────────────────────────────

    def _filtered_search(
        self,
        semantic_query: str,
        expanded:       str,
        filtered_records:        list,
        top_k:          int,
        use_bm25:       bool,
        verbose:        bool,
    ) -> list[int]:

        if not filtered_records:
            if verbose:
                print("   No documents matched the filters.")
            return []

        if verbose:
            print(f"   SQL pre-filter: {len(filtered_records)} candidates")

        ids   = [r[0] for r in filtered_records]
        texts = _build_texts(filtered_records)
        return self._rank_subset(expanded, ids, texts, top_k, use_bm25, semantic_query)


    # ── Retrieval: full-index path ────────────────────────────────────────────

    def _full_search(
        self,
        semantic_query: str,
        expanded:       str,
        top_k:          int,
        use_bm25:       bool,
    ) -> list[int]:
        """Search the entire FAISS index, optionally fusing with global BM25."""
        import sqlite3
        from .config import DB_PATH

        k         = top_k * 3
        q_vec     = self.models.encode_query(expanded)
        _, indices = self.models.index.search(q_vec, k)
        faiss_ids  = [int(self.models.doc_ids[i]) for i in indices[0]]

        if not (use_bm25 and HAS_BM25):
            return faiss_ids

        with sqlite3.connect(DB_PATH) as conn:
            rows = conn.execute(
                "SELECT id, title, abs_text, keyword_text FROM documents"
            ).fetchall()

        all_ids   = [r[0] for r in rows]
        all_texts = _build_texts(rows)
        scores    = bm25_score(semantic_query, all_texts)
        bm25_ids  = [all_ids[i] for i in np.argsort(scores)[::-1][:k]]

        return _rrf_merge(faiss_ids, bm25_ids, limit=top_k * 3)

    # ── Retrieval: rank a subset with a temporary FAISS index ────────────────

    def _rank_subset(
        self,
        expanded:       str,
        ids:            list[int],
        texts:          list[str],
        top_k:          int,
        use_bm25:       bool,
        semantic_query: str,
    ) -> list[int]:
        """Build a temporary FAISS index over *texts* and rank within it."""
        id_to_faiss_pos = {int(self.models.doc_ids[i]): i 
                       for i in range(len(self.models.doc_ids))}
    
        valid_ids = []
        vecs_list = []
        for doc_id in ids:
            pos = id_to_faiss_pos.get(doc_id)
            if pos is not None:
                vecs_list.append(self.models.index.reconstruct(int(pos)))
                valid_ids.append(doc_id)
        
        if not valid_ids:
            return ids[:top_k]
        
        vecs = np.array(vecs_list, dtype="float32")
        tmp = faiss.IndexFlatIP(vecs.shape[1])
        tmp.add(vecs)
        
        k = min(top_k * 3, len(valid_ids))
        q_vec = self.models.encode_query(expanded)
        _, fi = tmp.search(q_vec, k)
        faiss_ids = [valid_ids[i] for i in fi[0]]
        
        if not (use_bm25 and HAS_BM25):
            return faiss_ids
        
        scores = bm25_score(semantic_query, [texts[ids.index(vid)] for vid in valid_ids])
        bm25_ids = [valid_ids[i] for i in np.argsort(scores)[::-1][:k]]
        return _rrf_merge(faiss_ids, bm25_ids, limit=top_k * 3)
    

    # ── Logging helpers ───────────────────────────────────────────────────────

    def _log_query(
        self,
        original:  str,
        semantic:  str,
        expanded:  str,
        filters:   dict,
        parser:    str,
    ) -> None:
        print(process_farsi_text(f"\n🔎 Original : {original}"))
        if semantic != original:
            print(process_farsi_text(f"   Semantic : {semantic}"))
        if expanded != semantic:
            print(process_farsi_text(f"   Expanded : {expanded}"))
        if filters:
            print(process_farsi_text(f"   Filters  : {filters}"))
        print(f"   Parser   : {parser}  |  CE: {self.models._ce_key}")

    def _log_results(self, results: list, elapsed: float) -> None:
        print(f"\nTop {len(results)} results  ({elapsed:.2f}s)\n")
        for rank, (doc, score) in enumerate(results, 1):
            print("=" * 65)
            print(f"  #{rank}  score={score:.4f}  id={doc['id']}")
            print(process_farsi_text(f"  Title: {doc['title']}"))
            for field, label in (
                ("authors",     "Author(s)   "),
                ("advisors",    "Advisor(s)  "),
                ("co_advisors", "Co-advisor  "),
                ("university",  "University  "),
            ):
                if doc.get(field):
                    print(process_farsi_text(f"  {label}: {doc[field]}"))
            print(process_farsi_text(
                f"  Degree: {doc.get('degree','')} | "
                f"Year: {doc.get('year','')} | "
                f"Type: {doc.get('doc_type','')}"
            ))
            kw = doc.get("keyword_text", "")
            if kw:
                preview = kw[:80] + ("…" if len(kw) > 80 else "")
                print(process_farsi_text(f"  Keywords: {preview}"))