# Database access layer — all SQLite interactions live here.

import sqlite3
from .config import DB_PATH
from typing import List, Tuple, Dict, Union

# Column list is fetched once and cached to avoid repeated PRAGMA calls
_cached_columns: set | None = None


def get_columns() -> set:
    """Return the set of column names in the documents table (cached after first call)."""
    global _cached_columns
    if _cached_columns is None:
        conn = sqlite3.connect(DB_PATH)
        cur  = conn.cursor()
        cur.execute("PRAGMA table_info(documents)")
        _cached_columns = {row[1] for row in cur.fetchall()}
        conn.close()
    return _cached_columns


from typing import Dict, Union, List, Tuple
import sqlite3

def apply_filters(
    filters: Dict[str, Union[str, List[str], Tuple[int, int]]],
    join_operator: str = "AND"
) -> List[Tuple]:

    if join_operator not in ("AND", "OR"):
        raise ValueError("join_operator must be 'AND' or 'OR'")

    cols = get_columns()
    sql = "SELECT id, title, abs_text, keyword_text FROM documents WHERE 1=1"
    params: List = []

    # List to collect all condition strings
    conditions = []
    # List to collect all parameters in order
    condition_params = []

    def add_like_condition(
        column: str,
        values: Union[str, List[str]],
        fallback_columns: List[str] = None
    ):
        """Add LIKE conditions for a column, with optional fallback columns."""
        if not values:
            return

        value_list = [values] if isinstance(values, str) else values
        value_list = [v.strip() for v in value_list if v.strip()]

        if not value_list:
            return

        if column in cols:
            cond_parts = [f"{column} LIKE ?" for _ in value_list]
            condition_str = f"({' OR '.join(cond_parts)})"
            conditions.append(condition_str)
            condition_params.extend(f"%{v}%" for v in value_list)

        elif fallback_columns:
            or_parts = []
            for col in fallback_columns:
                or_parts.extend(f"{col} LIKE ?" for _ in value_list)
            if or_parts:
                condition_str = f"({' OR '.join(or_parts)})"
                conditions.append(condition_str)
                # Repeat values for each fallback column
                condition_params.extend(f"%{v}%" for v in value_list for _ in fallback_columns)

    # ────────────────────────────────────────────────
    # Collect conditions without modifying sql yet
    # ────────────────────────────────────────────────

    # Degree
    if "degree" in filters and "degree" in cols:
        add_like_condition("degree", filters["degree"])

    # Year range (tuple of two integers)
    if "year_range" in filters and "year" in cols:
        conditions.append("year BETWEEN ? AND ?")
        condition_params.extend(filters["year_range"])

    # Exact year(s) - single value or list
    elif "year_exact" in filters and "year" in cols:
        exact = filters["year_exact"]
        if isinstance(exact, (int, str)):
            exact_years = [int(exact)]
        else:
            exact_years = [int(y) for y in exact if str(y).strip().isdigit()]

        if exact_years:
            if len(exact_years) == 1:
                conditions.append("year = ?")
                condition_params.append(exact_years[0])
            else:
                placeholders = ", ".join(["?"] * len(exact_years))
                conditions.append(f"year IN ({placeholders})")
                condition_params.extend(exact_years)

    # Document type
    if "doc_type" in filters and "doc_type" in cols:
        add_like_condition("doc_type", filters["doc_type"])

    # University
    if "university" in filters:
        add_like_condition("university", filters["university"])

    # Authors
    if "authors" in filters:
        add_like_condition("authors", filters["authors"])

    # Advisors (with fallback to abstract/title)
    if "advisors" in filters:
        add_like_condition(
            "advisors",
            filters["advisors"],
            fallback_columns=["abs_text", "title"] if "advisors" not in cols else None
        )

    # Co-advisors
    if "co_advisors" in filters:
        add_like_condition("co_advisors", filters["co_advisors"])

    # Combine all collected conditions with chosen operator
    if conditions:
        join_str = f" {join_operator} "
        sql += " AND (" + join_str.join(conditions) + ")"

    # Execute query
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(condition_params))
        rows = cur.fetchall()
    finally:
        conn.close()

    return rows



def fetch_full_docs(doc_ids: list[int]) -> list[dict]:
    cols = get_columns()

    # Core columns that are always expected
    select = ["title", "abs_text", "keyword_text", "degree", "year", "doc_type"]

    # Optional columns — added only if present
    for col in ["advisors", "co_advisors", "authors", "university", "subject"]:
        if col in cols:
            select.append(col)

    col_str = ", ".join(select)
    conn    = sqlite3.connect(DB_PATH)
    cur     = conn.cursor()
    docs    = []

    for doc_id in doc_ids:
        cur.execute(f"SELECT {col_str} FROM documents WHERE id=?", (doc_id,))
        row = cur.fetchone()
        if row:
            doc = {"id": doc_id}
            for i, col in enumerate(select):
                doc[col] = row[i] or ""
            # Ensure all expected keys exist with empty-string defaults
            for key in ["abs_text", "degree", "year", "doc_type",
                        "advisors", "co_advisors", "authors", "subject", "university"]:
                doc.setdefault(key, "")
            docs.append(doc)

    conn.close()
    return docs