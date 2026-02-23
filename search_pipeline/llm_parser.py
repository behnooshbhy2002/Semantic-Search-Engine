# llm_parser.py
# Responsible for ONE thing: call the LLM and return (filters, keywords, success).
#
# All network I/O, prompt construction, JSON parsing, and schema conversion
# live here so engine.py stays free of API concerns.

from __future__ import annotations

import json
import logging

from .config import TEXT2SQL_API_KEY, TEXT2SQL_BASE_URL, TEXT2SQL_MODEL

log = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """شما یک موتور استخراج اطلاعات ساختاریافته هستید.
— اطلاعات را تغییر نده.
— فقط یک JSON معتبر برگردان، بدون هیچ توضیح اضافه‌ای.
— نوع سند را به این دو شکل استاندارد کن:
    • پارسا    ← هر نوع پایان‌نامه / رساله
    • پیشنهاده ← هر نوع پروپوزال / پیشنهادنامه
— اگر چند دانشگاه یا موسسه دیدی لیست همه را برگردان.
— اگر غلط املایی در کلمات کلیدی، نام دانشگاه و غیره وجود داشت، خودت درستش کن.
— فیلد keywords: کلمات کلیدی معنایی خالص کوئری (بدون متادیتا مثل سال/مقطع/دانشگاه).
— فیلد expanded_keywords: در صورت وجود keywords، حداکثر ۱۰ واژه یا عبارت مرتبط
  (بیشتر فارسی و کمی انگلیسی) که به بازیابی معنایی کمک می‌کنند.
— اگر اطلاعاتی برای یک فیلد وجود ندارد، مقدار null برگردان.

اسکیما خروجی:
{
  "doc_type":          ["پارسا" | "پیشنهاده"] | null,
  "degree":            ["دکتری" | "کارشناسی ارشد" | "کارشناسی"] | null,
  "year_exact":        [integer] | null,
  "year_from":         integer | null,
  "year_to":           integer | null,
  "university":        [string] | null,
  "authors":           [string] | null,
  "advisors":          [string] | null,
  "co_advisors":       [string] | null,
  "keywords":          string | null,
  "expanded_keywords": [string] | null
}"""


# ── LLM client (lazy import) ──────────────────────────────────────────────────

def _get_client():
    """Return an OpenAI-compatible client, or raise ImportError."""
    from openai import OpenAI          # lazy: don't require openai at import time
    return OpenAI(api_key=TEXT2SQL_API_KEY, base_url=TEXT2SQL_BASE_URL)


# ── Raw API call ──────────────────────────────────────────────────────────────

def _call_llm(query: str) -> dict:
    """
    Call the LLM and return the parsed JSON dict.
    Raises on any network / parse failure — callers decide how to handle it.
    """
    client = _get_client()
    resp = client.chat.completions.create(
        model=TEXT2SQL_MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": query},
        ],
    )
    raw = resp.choices[0].message.content.strip()

    # Strip optional markdown fences (```json … ```)
    if raw.startswith("```"):
        parts = raw.split("```")
        raw   = parts[1].lstrip("json").strip() if len(parts) > 1 else raw

    return json.loads(raw)


# ── Schema conversion ─────────────────────────────────────────────────────────

def _to_filter_dict(llm_data: dict) -> dict:
    """
    Convert the raw LLM JSON output into the internal filter format expected by
    database.apply_filters() and engine._filtered_search().

    Fields that support multiple values now receive list[str] directly
    (so they can be combined with OR in the SQL query).
    """
    f: dict = {}

    # Title - single string (if present)
    if title := llm_data.get("title"):
        if isinstance(title, str) and (cleaned := title.strip()):
            f["title"] = cleaned

    # Year handling (range or exact)
    year_from  = llm_data.get("year_from")
    year_to    = llm_data.get("year_to")
    year_exact = llm_data.get("year_exact")

    if year_from and year_to:
        try:
            f["year_range"] = (int(year_from), int(year_to))
        except (ValueError, TypeError):
            pass
    elif year_exact:
        try:
            f["year_exact"] = int(year_exact)
        except (ValueError, TypeError):
            pass

    elif year_exact is not None:
        try:
            # اگر تک عدد بود → int
            if isinstance(year_exact, (int, str)):
                cleaned = int(year_exact)
                f["year_exact"] = cleaned
            
            # اگر لیست بود → لیست اعداد معتبر
            elif isinstance(year_exact, (list, tuple)):
                cleaned_years = []
                for y in year_exact:
                    try:
                        val = int(y)
                        cleaned_years.append(val)
                    except (ValueError, TypeError):
                        pass
                if cleaned_years:
                    f["year_exact"] = (
                        cleaned_years[0] if len(cleaned_years) == 1 else cleaned_years
                    )
                    
        except Exception:
            pass

    # ────────────────────────────────────────────────
    # Fields that now accept list[str] in apply_filters
    # ────────────────────────────────────────────────

    # doc_type
    if value := llm_data.get("doc_type"):
        items = value if isinstance(value, list) else [value]
        cleaned = [str(item).strip() for item in items if item and str(item).strip()]
        if cleaned:
            f["doc_type"] = cleaned if len(cleaned) > 1 else cleaned[0]

    # degree
    if value := llm_data.get("degree"):
        items = value if isinstance(value, list) else [value]
        cleaned = [str(item).strip() for item in items if item and str(item).strip()]
        if cleaned:
            f["degree"] = cleaned if len(cleaned) > 1 else cleaned[0]

    # university
    if value := llm_data.get("university"):
        items = value if isinstance(value, list) else [value]
        cleaned = [str(item).strip() for item in items if item and str(item).strip()]
        if cleaned:
            f["university"] = cleaned if len(cleaned) > 1 else cleaned[0]

    # advisors / co_advisors / authors
    for field in ("advisors", "co_advisors", "authors"):
        value = llm_data.get(field)
        if not value:
            continue

        if isinstance(value, str):
            # Split common Persian/English name separators
            import re
            split_pattern = r"[،,؛;]\s*|\s+و\s+"
            names = [n.strip() for n in re.split(split_pattern, value) if n.strip()]
        else:
            # Already a list (or list-like)
            names = [
                str(item).strip()
                for item in (value if isinstance(value, (list, tuple)) else [value])
                if item and str(item).strip()
            ]

        if names:
            f[field] = names   # list[str] → apply_filters will use OR

    return f


# ── Public interface ──────────────────────────────────────────────────────────

class LLMParseResult:
    """Value object returned by extract()."""
    __slots__ = ("filters", "keywords", "expanded_keywords", "success")

    def __init__(
        self,
        filters:           dict,
        keywords:          str | None,
        expanded_keywords: list[str] | None,
        success:           bool,
    ):
        self.filters           = filters
        self.keywords          = keywords
        self.expanded_keywords = expanded_keywords   # list[str] from LLM field
        self.success           = success


_UNAVAILABLE = LLMParseResult({}, None, None, False)


def extract(query: str) -> LLMParseResult:
    """
    Parse *query* with the LLM and return a LLMParseResult.

    Returns LLMParseResult(success=False) when:
      - API key is not configured
      - openai package is not installed
      - network / auth / JSON parse error occurs
    Errors are logged as warnings; no exceptions propagate.
    """
    if not TEXT2SQL_API_KEY:
        log.debug("LLM parser skipped: TEXT2SQL_API_KEY not set.")
        return _UNAVAILABLE

    try:
        llm_data = _call_llm(query)
    except ImportError:
        log.warning("openai package not installed — LLM parser unavailable.")
        return _UNAVAILABLE
    except Exception as exc:
        log.warning("LLM call failed: %s", exc)
        return _UNAVAILABLE

    filters = _to_filter_dict(llm_data)

    raw_kw   = (llm_data.get("keywords") or "").strip()
    keywords = raw_kw.replace(",", " ").replace("،", " ").strip() or None

    # expanded_keywords: list[str] supplied directly by the LLM
    raw_exp = llm_data.get("expanded_keywords") or []
    expanded_keywords = [
        t.strip() for t in (raw_exp if isinstance(raw_exp, list) else [])
        if t and str(t).strip()
    ] or None

    return LLMParseResult(
        filters=filters,
        keywords=keywords,
        expanded_keywords=expanded_keywords,
        success=True,
    )