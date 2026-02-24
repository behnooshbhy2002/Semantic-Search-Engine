# Query parser: extracts structured metadata filters from a natural-language Persian query.
#
# University detection strategy (replaces fragile regex):
#   At startup, load all distinct university names from the DB into a list.
#   When a query contains a university trigger word (دانشگاه, موسسه, ...),
#   find the university name in the DB that has the highest character-level
#   overlap with the words following the trigger. This is robust to:
#     - multi-word names ("پیام نور کرج", "آزاد اسلامی واحد تهران مرکز")
#     - minor spelling differences
#     - extra words between the trigger and the name

import re
from .config import UNIVERSITY_TRIGGERS

# ---------------------------------------------------------------------------
# Loaded once at import time (or refreshed by calling init_university_list)
# ---------------------------------------------------------------------------
_university_list: list[str] = []   # filled in by engine at startup


def init_university_list(names: list[str]) -> None:
    """Feed the full university name list from the DB into the parser."""
    global _university_list
    _university_list = [n.strip() for n in names if n.strip()]


# ---------------------------------------------------------------------------
# Person-name extraction patterns
# ---------------------------------------------------------------------------
_PERSON_PATTERNS = [
    # "استاد راهنما دکتر X" or "راهنما X"
    (
        r"(?:استاد\s+راهنما|راهنمای?)\s*:?\s*(?:دکتر|استاد|مهندس|پروفسور)?\s*"
        r"([آ-ی][آ-ی\s]{1,25}[آ-ی])"
        r"(?=\s*(?:و|یا|که|با|در|از|برای|پایان|ارشد|دکتری|$))",
        "advisors",
    ),
    # bare "دکتر X" (no explicit راهنما/مشاور trigger)
    (
        r"(?<!راهنما\s)(?<!مشاور\s)"
        r"(?:دکتر|مهندس|پروفسور)\s+"
        r"([آ-ی][آ-ی\s]{1,25}[آ-ی])"
        r"(?=\s*(?:و|یا|که|با|در|از|راهنما|مشاور|$))",
        "advisors",
    ),
    # "استاد مشاور X" or "مشاور X"
    (
        r"(?:استاد\s+مشاور|مشاور)\s*:?\s*(?:دکتر|استاد|مهندس|پروفسور)?\s*"
        r"([آ-ی][آ-ی\s]{1,25}[آ-ی])"
        r"(?=\s*(?:و|یا|که|با|در|از|$))",
        "co_advisors",
    ),
    # "نوشته X", "اثر X", "توسط X", etc.
    (
        r"(?:نوشته|پدیدآور|نویسنده|توسط|اثر)\s*:?\s*"
        r"([آ-ی][آ-ی\s]{1,25}[آ-ی])"
        r"(?=\s*(?:و|یا|که|با|در|از|$))",
        "authors",
    ),
]

_TRIM_TAIL = re.compile(r"\s+(?:راهنما|مشاور|استاد|دانشگاه|سال|ارشد|دکتری|پروپوزال|پایان).*$")
_STOP_TAIL = re.compile(r"\s+(?:و|یا|که|با|در|از|برای|را|است|دانشگاه)$")
_BLACKLIST  = re.compile(r"(?:راهنما|مشاور|استاد|دانشگاه|دکتری|پروپوزال|پایان)")


# ---------------------------------------------------------------------------
# University fuzzy matching
# ---------------------------------------------------------------------------

def _char_overlap_score(a: str, b: str) -> float:
    """
    Simple character-bigram Jaccard similarity between two strings.
    Fast and works well for Persian names that differ by a word or two.
    """
    def bigrams(s: str) -> set:
        s = s.replace(" ", "")
        return {s[i:i+2] for i in range(len(s) - 1)} if len(s) >= 2 else {s}

    bg_a = bigrams(a)
    bg_b = bigrams(b)
    if not bg_a or not bg_b:
        return 0.0
    return len(bg_a & bg_b) / len(bg_a | bg_b)


def _find_university_in_query(query: str) -> str | None:
    """
    Detect a university mention and return the best-matching DB name.

    Steps:
      1. Look for a university trigger word in the query.
      2. Extract a candidate window of text following the trigger (up to 10 words).
      3. Score every DB university name against that window using bigram Jaccard.
      4. Return the DB name with the highest score (if score > 0.15, else None).

    This approach handles multi-word names and minor spelling differences
    without any regex fragility.
    """
    if not _university_list:
        # Fallback to a simple regex when the DB list hasn't been loaded
        return _university_regex_fallback(query)

    for trigger in UNIVERSITY_TRIGGERS:
        idx = query.find(trigger)
        if idx == -1:
            continue

        # Grab up to 10 words after the trigger as the candidate window
        after      = query[idx + len(trigger):].strip()
        words      = after.split()[:10]
        window     = " ".join(words)

        if not window:
            continue


        scores = []
        for uni_name in _university_list:
            score = _char_overlap_score(window, uni_name)
            if score >= 0.15:   # threshold
                scores.append((uni_name, score))

        # sort descending by score
        scores.sort(key=lambda x: x[1], reverse=True)

        # take top 3 (or 4)
        top_k = 3
        best_matches = scores[:top_k]
        best_names = [name for name, _ in best_matches]
        return best_names

    return None


def _university_regex_fallback(query: str) -> str | None:
    """Regex-based extraction used only when the DB list is unavailable."""
    for trigger in UNIVERSITY_TRIGGERS:
        pattern = (
            rf"{trigger}\s+"
            r"([آ-ی\w][آ-ی\w\s]{1,60}?)"
            r"(?=\s*(?:سال|مقطع|ارشد|دکتری|کارشناسی|پروپوزال|پایان|با|که|و|یا|\d|$))"
        )
        m = re.search(pattern, query)
        if m:
            return m.group(1).strip()
    return None


# ---------------------------------------------------------------------------
# SQL token stripping
# ---------------------------------------------------------------------------

# Patterns to remove from the query before semantic search.
# Order matters: longer/more-specific patterns first.
_SQL_STRIP_PATTERNS = [
    # Year range: "بین سال X تا Y" or just "سال X تا Y"
    r"بین\s+سال\s+\d{4}\s+تا\s+\d{4}",
    r"سال\s+\d{4}\s+تا\s+\d{4}",
    r"سال\s+\d{4}",
    r"\d{4}",                              # bare year numbers
    # Degree
    r"کارشناسی\s+ارشد",
    r"کارشناسی",
    r"دکتری",
    r"ارشد",
    # Document type
    r"پروپوزال",
    r"پیشنهاده",
    r"پیشنهادنامه",
    r"پایان‌نامه",
    r"پایاننامه",
    r"رساله",
    r"پارسا",
    # University trigger + name (replace the whole phrase)
    r"(?:" + "|".join(UNIVERSITY_TRIGGERS) + r")\s+[آ-ی\w][آ-ی\w\s]{0,60}?(?=\s|$)",
    # Person trigger words (keep the name — only strip the label)
    r"استاد\s+راهنما",
    r"راهنمای?",
    r"استاد\s+مشاور",
    r"مشاور",
    r"نوشته|پدیدآور|نویسنده|توسط|اثر",
    r"دکتر|مهندس|پروفسور",
    # Connective filler words that become meaningless once filters are stripped
    r"\bبین\b",
    r"\bتا\b",
    r"\bدر\b",
    r"\bبا\b",
    r"\bاز\b",
    r"\bبرای\b",
    r"\bسال\b",
]

_SQL_STRIP_RE = re.compile("|".join(f"(?:{p})" for p in _SQL_STRIP_PATTERNS))


import re

def strip_filter_tokens(query: str, filters: dict) -> str:
    """
    Remove all filter values (word by word) from the query text.

    The goal is to eliminate metadata terms already captured as SQL filters
    so that the remaining query represents only the semantic intent.

    If filters is empty, the original query is returned unchanged.
    """

    if not filters:
        return query

    cleaned = _SQL_STRIP_RE.sub(" ", query)

    for value in filters.values():
        if not value:
            continue

        # Support both single values and lists of values
        if isinstance(value, list):
            values = value
        else:
            values = [value]

        for v in values:
            # Split filter value into individual tokens
            for token in str(v).split():
                # Remove exact token match (safer boundary for Persian text)
                cleaned = re.sub(
                    rf'(?<!\S){re.escape(token)}(?!\S)',
                    ' ',
                    cleaned
                )

    # Collapse multiple spaces
    cleaned = re.sub(r'\s{2,}', ' ', cleaned).strip()

    # If stripping removed everything, fall back to original query
    return cleaned


# ---------------------------------------------------------------------------
# Main filter parser
# ---------------------------------------------------------------------------

def _extract_persons(query: str) -> dict:
    """Run person-name patterns against the query; return {field: name} pairs."""
    found = {}
    for pattern, field in _PERSON_PATTERNS:
        if field in found:
            continue
        m = re.search(pattern, query)
        if not m:
            continue
        name = m.group(1).strip()
        name = _TRIM_TAIL.sub("", name).strip()
        name = _STOP_TAIL.sub("", name).strip()
        if _BLACKLIST.search(name) or len(name) < 3:
            continue
        found[field] = name
    return found


def parse_filters(query: str) -> dict:
    """
    Parse a Persian natural-language query and return a dict of metadata filters.

    Supported filters:
        year_range   — "بین سال ۱۴۰۲ تا ۱۴۰۴"  -> (1402, 1404)
        year_exact   — "سال 1403"               -> 1403
        degree       — دکتری / ارشد / کارشناسی
        doc_type     — پروپوزال -> "پیشنهاده"  |  پایان‌نامه -> "پارسا"
        university   — best-matching DB university name (fuzzy)
        advisors     — "استاد راهنما دکتر X"
        co_advisors  — "استاد مشاور X"
        authors      — "نوشته X"

    Example:
        parse_filters("پروپوزال دکتری دانشگاه پیام نور کرج سال ۱۴۰۳")
        # -> {'doc_type': 'پیشنهاده', 'degree': 'دکتری',
        #     'university': 'دانشگاه پیام نور کرج', 'year_exact': 1403}
    """
    filters = {}

    # Convert Persian/Arabic-Indic digits to ASCII for reliable regex matching
    digit_map = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
    q = query.translate(digit_map)

    # --- Year ---
    years = re.findall(r"\b(1[34]\d{2})\b", q)
    if len(years) >= 2:
        filters["year_range"] = (int(years[0]), int(years[1]))
    elif len(years) == 1:
        filters["year_exact"] = int(years[0])

    # --- Degree ---
    if "دکتری" in query:
        filters["degree"] = "دکتری"
    elif "کارشناسی ارشد" in query or "ارشد" in query:
        filters["degree"] = "ارشد"
    elif "کارشناسی" in query:
        filters["degree"] = "کارشناسی"

    # --- Document type ---
    if any(w in query for w in ["پروپوزال", "پیشنهاده", "پیشنهادنامه"]):
        filters["doc_type"] = "پیشنهاده"
    elif any(w in query for w in ["پایان‌نامه", "پایاننامه", "پارسا", "رساله"]):
        filters["doc_type"] = "پارسا"

    # --- University (fuzzy match against DB list) ---
    uni = _find_university_in_query(query)
    if uni:
        filters["university"] = uni

    # --- Person names ---
    filters.update(_extract_persons(query))

    return filters