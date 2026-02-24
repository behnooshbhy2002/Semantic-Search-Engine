# llm_parser.py
# Responsible for ONE thing: call the LLM and return (filters, keywords, success).
#
# All network I/O, prompt construction, JSON parsing, and schema conversion
# live here so engine.py stays free of API concerns.

from __future__ import annotations

import json
import logging

# فرض می‌کنیم این مقادیر در config.py تعریف شده‌اند
from .config import (
    TEXT2SQL_API_KEY,      # ← کلید جدید برای Groq
    TEXT2SQL_MODEL,        # مثلاً "qwen/qwen3-32b" یا "llama-3.1-70b-versatile" و ...
)

log = logging.getLogger(__name__)

# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """شما یک موتور استخراج اطلاعات ساختاریافته هستید.
— اطلاعات را تغییر نده.
— فقط یک JSON معتبر برگردان، بدون هیچ توضیح اضافه‌ای.
— نوع سند را به این دو شکل استاندارد کن:
    • پارسا    ← هر نوع پایان‌نامه / رساله
    • پیشنهاده ← هر نوع پروپوزال / پیشنهادنامه
— اگر چند دانشگاه یا موسسه دیدی لیست همه را برگردان.
-  همچنین اگر کاربر دانشکده نوشته بود هم در فیلد دانشگاه قرارش بده
—  اگر غلط املایی در کلمات کلیدی، نام دانشگاه و غیره وجود داشت، خودت درستش کن ولی سال رو به میلادی تغییر نده.
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
    """Return a Groq client, or raise ImportError."""
    from groq import Groq          # lazy import
    if not TEXT2SQL_API_KEY:
        raise ValueError("Groq API key is not set in config")
    return Groq(api_key=TEXT2SQL_API_KEY)


# ── Raw API call ──────────────────────────────────────────────────────────────

def _call_llm(query: str) -> dict:
    """
    Call the Groq LLM and return the parsed JSON dict.
    Raises on any network / parse failure — callers decide how to handle it.
    """
    client = _get_client()

    resp = client.chat.completions.create(
        model=TEXT2SQL_MODEL,
        temperature=0.0,               # برای استخراج ساختار یافته بهتر است پایین باشد
        max_tokens=1024,               # معمولاً برای JSON کافی است
        top_p=0.95,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": query},
        ],
        # stream=False → می‌توانید True کنید و استریم را مدیریت کنید
        stream=False,
    )

    raw = resp.choices[0].message.content.strip()

    # حذف فنس‌های مارک‌داون احتمالی (```json ... ```)
    if raw.startswith("```"):
        parts = raw.split("```", 2)
        if len(parts) > 2:
            raw = parts[1].lstrip("json \n").rstrip("\n ")
        else:
            raw = parts[-1].strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log.warning("JSON parse error from Groq response: %s\nRaw: %s", e, raw)
        raise


# ── Schema conversion ─────────────────────────────────────────────────────────

# این بخش بدون تغییر باقی می‌ماند (یا تغییرات جزئی اگر لازم باشد)
# فقط برای کامل بودن دوباره می‌گذارم

def _to_filter_dict(llm_data: dict) -> dict:
    f: dict = {}

    # year handling
    year_from  = llm_data.get("year_from")
    year_to    = llm_data.get("year_to")
    year_exact = llm_data.get("year_exact")

    if year_from and year_to:
        try:
            f["year_range"] = (int(year_from), int(year_to))
        except:
            pass
    elif year_exact:
        try:
            if isinstance(year_exact, (int, str)):
                f["year_exact"] = int(year_exact)
            elif isinstance(year_exact, (list, tuple)):
                cleaned = [int(y) for y in year_exact if str(y).strip().isdigit()]
                if cleaned:
                    f["year_exact"] = cleaned[0] if len(cleaned) == 1 else cleaned
        except:
            pass

    # لیست‌دارها
    for field in ("doc_type", "degree", "university"):
        if value := llm_data.get(field):
            items = value if isinstance(value, list) else [value]
            cleaned = [str(i).strip() for i in items if str(i).strip()]
            if cleaned:
                f[field] = cleaned if len(cleaned) > 1 else cleaned[0]

    # نام‌ها (اساتید، نویسندگان و ...)
    import re
    split_pattern = r"[،,؛;]\s*|\s+و\s+"

    for field in ("advisors", "co_advisors", "authors"):
        value = llm_data.get(field)
        if not value:
            continue
        if isinstance(value, str):
            names = [n.strip() for n in re.split(split_pattern, value) if n.strip()]
        else:
            names = [str(i).strip() for i in (value if isinstance(value, (list,tuple)) else [value])]
        if names:
            f[field] = names

    return f


# ── Public interface ──────────────────────────────────────────────────────────

class LLMParseResult:
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
        self.expanded_keywords = expanded_keywords
        self.success           = success


_UNAVAILABLE = LLMParseResult({}, None, None, False)


def extract(query: str) -> LLMParseResult:
    if not TEXT2SQL_API_KEY:
        log.debug("Groq LLM parser skipped: API key not set.")
        return _UNAVAILABLE

    try:
        llm_data = _call_llm(query)
    except ImportError:
        log.warning("groq package not installed — LLM parser unavailable.")
        return _UNAVAILABLE
    except Exception as exc:
        log.warning("Groq LLM call failed: %s", exc, exc_info=True)
        return _UNAVAILABLE

    filters = _to_filter_dict(llm_data)

    raw_kw = (llm_data.get("keywords") or "").strip()
    keywords = raw_kw.replace(",", " ").replace("،", " ").strip() or None

    raw_exp = llm_data.get("expanded_keywords") or []
    expanded_keywords = [
        t.strip() for t in (raw_exp if isinstance(raw_exp, list) else [raw_exp])
        if t and str(t).strip()
    ] or None

    return LLMParseResult(
        filters=filters,
        keywords=keywords,
        expanded_keywords=expanded_keywords,
        success=True,
    )