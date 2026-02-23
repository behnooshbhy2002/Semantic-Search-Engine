# سرور Flask — REST API برای پایپلاین جستجو
#
# endpoint‌ها:
#   GET  /api/health          — بررسی سلامت سرور
#   GET  /api/models          — لیست cross-encoder های موجود
#   POST /api/search          — جستجوی اصلی
#   GET  /api/schema          — ستون‌های دیتابیس

from flask import Flask, request, jsonify
from flask_cors import CORS

from Search_Pipeline import DB_PATH, FAISS_INDEX, DOC_IDS_PATH, Models, SearchEngine
from Search_Pipeline.config import CROSS_ENCODER_REGISTRY, DEFAULT_CROSS_ENCODER

app = Flask(__name__)
CORS(app)

print("در حال راه‌اندازی سرور...")
models = Models()
models.load_index(FAISS_INDEX, DOC_IDS_PATH)
engine = SearchEngine(models)
print("✅ سرور آماده‌ست.\n")


@app.get("/api/health")
def health():
    """بررسی می‌کنه سرور درسته یا نه."""
    return jsonify({"status": "ok", "db": DB_PATH})


@app.get("/api/models")
def list_models():
    """
    لیست cross-encoder های قابل انتخاب رو برمی‌گردونه.

    خروجی:
        [{"key": "bge-base", "label": "...", "default": true}, ...]
    """
    result = []
    for key, info in CROSS_ENCODER_REGISTRY.items():
        result.append({
            "key":     key,
            "label":   info["label"],
            "model":   info["model"],
            "default": key == DEFAULT_CROSS_ENCODER,
        })
    return jsonify({"models": result})


@app.post("/api/search")
def search():
    """
    جستجو رو اجرا می‌کنه.

    body (JSON):
        query        — عبارت جستجو (اجباری)
        top_k        — تعداد نتایج (پیش‌فرض: 10)
        use_bm25     — آیا BM25 هم استفاده بشه (پیش‌فرض: true)
        parser_mode  — "llm" یا "rule" (پیش‌فرض: "llm")
        ce_key       — کلید cross-encoder از /api/models (پیش‌فرض: مدل فعلی)

    خروجی: لیست نتایج با تمام فیلدها + parser_used
    """
    body         = request.get_json(force=True) or {}
    query        = (body.get("query") or "").strip()
    top_k        = int(body.get("top_k", 10))
    use_bm25     = bool(body.get("use_bm25", True))
    use_expand   = bool(body.get("use_expand", True))
    use_or       = bool(body.get("use_or", False))
    parser_mode  = body.get("parser_mode", "llm")    # "llm" | "rule"
    ce_key       = body.get("ce_key") or None        # None = keep current model

    if not query:
        return jsonify({"error": "query نمی‌تونه خالی باشه"}), 400

    if parser_mode not in ("llm", "rule"):
        return jsonify({"error": "parser_mode باید 'llm' یا 'rule' باشه"}), 400

    results, expanded_query, parser_used, or_used = engine.search(
        query,
        top_k=top_k,
        use_bm25=use_bm25,
        use_expand=use_expand,
        use_or=use_or,
        parser_mode=parser_mode,
        ce_key=ce_key,
        verbose=True,
    )

    payload = []
    for doc, score in results:
        payload.append({
            "id":           doc.get("id"),
            "title":        doc.get("title", ""),
            "abs_text":     doc.get("abs_text", ""),
            "keyword_text": doc.get("keyword_text", ""),
            "degree":       doc.get("degree", ""),
            "year":         doc.get("year", ""),
            "doc_type":     doc.get("doc_type", ""),
            "authors":      doc.get("authors", ""),
            "advisors":     doc.get("advisors", ""),
            "co_advisors":  doc.get("co_advisors", ""),
            "university":   doc.get("university", ""),
            "subject":      doc.get("subject", ""),
            "score":        round(score, 4),
        })

    return jsonify({
        "query":          query,
        "expanded_query": expanded_query,
        "parser_used":    parser_used,
        "or_used":        or_used,
        "ce_key":         models._ce_key,
        "count":          len(payload),
        "results":        payload,
    })


@app.get("/api/schema")
def schema():
    """ستون‌های جدول documents رو برمی‌گردونه."""
    from search_pipeline.database import get_schema
    cols = get_schema()
    return jsonify({"columns": [{"name": c, "type": t} for c, t in cols]})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)