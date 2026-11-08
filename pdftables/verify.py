"""Prove the extraction: look up every extracted number in the PDF's own text layer.

Table extraction can silently shift a value to the wrong row, merge two cells or drop a
digit. The PDF's text layer is read separately (no table detection involved), so a number
found there was really printed in the document:

    found        the number appears in the text of the same page
    elsewhere    it appears in the PDF, but on another page
    loose        its digits appear once spaces and commas are ignored
    NOT FOUND    not in the PDF: check this cell
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from pdftables.numbers import numbers_in_text


def _page_texts(pdf: str | Path) -> list[str]:
    import pdfplumber
    with pdfplumber.open(str(pdf)) as doc:
        return [page.extract_text() or "" for page in doc.pages]


def verify(df: pd.DataFrame, pdf: str | Path, columns=None) -> pd.DataFrame:
    """One row per numeric cell with its status. Uses the 'page' column when present."""
    pages = _page_texts(pdf)
    page_numbers = [numbers_in_text(t) for t in pages]
    all_numbers = set().union(*page_numbers) if page_numbers else set()
    all_digits = re.sub(r"[\s, ]", "", "".join(pages))
    def is_number(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v

    # Columns holding parsed numbers (a stray text cell, e.g. a repeated header, is allowed).
    columns = columns or [c for c in df.columns if c != "page" and df[c].map(is_number).any()]

    rows = []
    for idx, r in df.iterrows():
        for c in columns:
            v = r[c]
            if not is_number(v):
                continue
            key = round(abs(float(v)), 2)
            page = int(r["page"]) if "page" in df.columns and str(r["page"]).isdigit() else None
            if page and key in page_numbers[page - 1]:
                status = "found"
            elif key in all_numbers:
                status = "elsewhere" if page else "found"
            elif (f"{key:.2f}".rstrip("0").rstrip(".")).replace(".", "") in all_digits.replace(".", ""):
                status = "loose"
            else:
                status = "NOT FOUND"
            rows.append({"row": idx, "column": c, "value": v, "page": page, "status": status})
    return pd.DataFrame(rows, columns=["row", "column", "value", "page", "status"])


def summary(report: pd.DataFrame) -> str:
    if report.empty:
        return "no numeric cells to verify"
    counts = report["status"].value_counts()
    total = len(report)
    parts = [f"{counts.get(s, 0)} {s}" for s in ["found", "elsewhere", "loose", "NOT FOUND"] if counts.get(s, 0)]
    return f"{total} numbers checked: " + ", ".join(parts)
