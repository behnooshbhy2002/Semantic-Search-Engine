# Model loader — loads bi-encoder, one cross-encoder (selectable), and FAISS index at startup.
#
# The cross-encoder is now chosen by the user from the UI dropdown.
# A single instance is kept loaded; if the user switches models, the engine
# hot-swaps it on the next request (lazy load + cache).

import numpy as np
import faiss
from sentence_transformers import SentenceTransformer, CrossEncoder
from .config import BI_ENCODER_MODEL, CROSS_ENCODER_REGISTRY, DEFAULT_CROSS_ENCODER


class Models:
    """
    Container for all ML models and the FAISS index.

    Attributes:
        bi_encoder       — SentenceTransformer for dense retrieval
        cross_encoder    — currently active CrossEncoder for reranking
        _ce_key          — registry key of the currently loaded cross-encoder
        index            — FAISS flat inner-product index
        doc_ids          — numpy array: FAISS position i -> document ID
    """

    def __init__(self):
        print(f"Loading bi-encoder ({BI_ENCODER_MODEL})...")
        self.bi_encoder = SentenceTransformer(BI_ENCODER_MODEL)

        # Load the default cross-encoder at startup
        self._ce_key      = DEFAULT_CROSS_ENCODER
        ce_model_name     = CROSS_ENCODER_REGISTRY[DEFAULT_CROSS_ENCODER]["model"]
        print(f"Loading cross-encoder ({ce_model_name})...")
        self.cross_encoder = CrossEncoder(ce_model_name)

        print("✅ Models ready.\n")
        self.index   = None
        self.doc_ids = None

    def load_index(self, index_path: str, doc_ids_path: str) -> None:
        """Load the pre-built FAISS index and its document ID mapping from disk."""
        self.index   = faiss.read_index(index_path)
        self.doc_ids = np.load(doc_ids_path)
        print(f"✅ FAISS index loaded: {self.index.ntotal} vectors.\n")

    def set_cross_encoder(self, key: str) -> None:
        """
        Hot-swap the cross-encoder to the one identified by *key*.
        No-op if the requested model is already loaded.
        """
        if key == self._ce_key:
            return
        if key not in CROSS_ENCODER_REGISTRY:
            raise ValueError(f"Unknown cross-encoder key: {key!r}. "
                             f"Valid keys: {list(CROSS_ENCODER_REGISTRY)}")
        model_name = CROSS_ENCODER_REGISTRY[key]["model"]
        print(f"🔄 Switching cross-encoder to {model_name}...")
        self.cross_encoder = CrossEncoder(model_name)
        self._ce_key       = key
        print("✅ Cross-encoder switched.\n")

    def encode_query(self, text: str) -> np.ndarray:
        """Embed a query string and L2-normalise the resulting vector."""
        vec = self.bi_encoder.encode(
            ["query: " + text],
            convert_to_numpy=True,
            show_progress_bar=False,
        ).astype("float32")
        faiss.normalize_L2(vec)
        return vec

    def encode_passages(self, texts: list[str]) -> np.ndarray:
        """Embed a list of passage strings and L2-normalise all vectors."""
        vecs = self.bi_encoder.encode(
            ["passage: " + t for t in texts],
            convert_to_numpy=True,
            show_progress_bar=False,
            batch_size=16,
        ).astype("float32")
        faiss.normalize_L2(vecs)
        return vecs

    def rerank(
        self,
        query: str,
        docs: list[dict],
    ) -> list[tuple[dict, float]]:
        """
        Rerank documents with the currently active cross-encoder.

        Args:
            query — the search query (SQL filter tokens stripped out)
            docs  — candidate documents
        """
        pairs = [
            (query, d["title"] + " " + d.get("abs_text", "") + " " + d.get("keyword_text", ""))
            for d in docs
        ]
        scores = self.cross_encoder.predict(pairs, batch_size=4, show_progress_bar=False)
        return sorted(zip(docs, scores.tolist()), key=lambda x: -x[1])