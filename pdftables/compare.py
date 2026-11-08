"""Run pdfplumber and Camelot on the same PDF and show where they disagree.

Each engine misses different things (Camelot, for example, finds no table on a page that
holds a single table row). Comparing the numbers both found is a quick way to spot rows
that one of them dropped or mangled.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd

from pdftables.extract import extract_tables, to_numbers


def _number_bag(df: pd.DataFrame) -> Counter:
    nums = to_numbers(df.drop(columns=["page"], errors="ignore"))
    values = []
    for c in nums.columns:
        values += [round(float(v), 2) for v in nums[c]
                   if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v]
    return Counter(values)


def compare_engines(pdf, pages=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(summary, differences): rows/numbers per engine, and numbers only one engine found."""
    results, bags = {}, {}
    for engine in ("pdfplumber", "camelot"):
        df = extract_tables(pdf, engine=engine, pages=pages)
        results[engine] = df
        bags[engine] = _number_bag(df)
    summary = pd.DataFrame([
        {"engine": e, "rows": len(df), "columns": df.shape[1] - 1, "numbers": sum(bags[e].values())}
        for e, df in results.items()
    ])
    only_p = bags["pdfplumber"] - bags["camelot"]
    only_c = bags["camelot"] - bags["pdfplumber"]
    diffs = pd.DataFrame(
        [{"value": v, "times": n, "found_only_by": "pdfplumber"} for v, n in only_p.items()] +
        [{"value": v, "times": n, "found_only_by": "camelot"} for v, n in only_c.items()],
        columns=["value", "times", "found_only_by"],
    )
    return summary, diffs
