"""Extract every table from a PDF into one clean DataFrame.

Handles what goes wrong in practice with multi-page report tables:
  * tables that continue across pages repeat the header row on every page -> kept once
  * text wrapped inside a cell comes back with line breaks -> joined with a space
  * pdfplumber and Camelot each miss different things -> pick either, or compare both
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ENGINES = ("pdfplumber", "camelot")


def _pages_arg(pages) -> list[int] | None:
    """'1,3-5' -> [1, 3, 4, 5]; None -> all pages."""
    if pages is None:
        return None
    if isinstance(pages, (list, tuple)):
        return [int(p) for p in pages]
    out = []
    for part in str(pages).split(","):
        if "-" in part:
            a, b = part.split("-")
            out.extend(range(int(a), int(b) + 1))
        elif part.strip():
            out.append(int(part))
    return out


def _norm(row) -> list[str]:
    def text(c):
        return "" if c is None or (isinstance(c, float) and c != c) else str(c)
    return [re.sub(r"\s+", " ", text(c)).strip() for c in row]


def raw_tables(pdf: str | Path, engine: str = "pdfplumber", pages=None) -> list[pd.DataFrame]:
    """One DataFrame per table found, page by page, cells as strings."""
    pdf = str(pdf)
    if not Path(pdf).is_file():
        raise FileNotFoundError(pdf)
    wanted = _pages_arg(pages)
    tables: list[pd.DataFrame] = []
    if engine == "pdfplumber":
        import pdfplumber
        with pdfplumber.open(pdf) as doc:
            for number, page in enumerate(doc.pages, start=1):
                if wanted and number not in wanted:
                    continue
                for t in page.extract_tables():
                    tables.append(pd.DataFrame(t).assign(_page=number))
    elif engine == "camelot":
        import camelot
        found = camelot.read_pdf(pdf, pages=",".join(map(str, wanted)) if wanted else "all", flavor="lattice")
        for t in found:
            tables.append(t.df.assign(_page=int(t.page)))
    else:
        raise ValueError(f"engine must be one of {ENGINES}")
    return tables


def extract_tables(pdf: str | Path, engine: str = "pdfplumber", pages=None,
                   header: bool = True, keep_page: bool = True) -> pd.DataFrame:
    """All tables of the PDF stacked into one DataFrame.

    header=True uses the first row of the first table as column names and drops the same row
    wherever it is repeated on later pages. keep_page adds a 'page' column.
    """
    tables = raw_tables(pdf, engine, pages)
    if not tables:
        raise ValueError(f"No tables found in {pdf} with {engine}")

    pages_col = [t.pop("_page") for t in tables]
    first_row = _norm(tables[0].iloc[0])
    cleaned = []
    for i, (t, pg) in enumerate(zip(tables, pages_col)):
        t = t.copy()
        t["_page"] = pg.values
        if header and len(t) and _norm(t.drop(columns="_page").iloc[0]) == first_row:
            t = t.iloc[1:]  # header row (first table) or its repeat (later pages)
        cleaned.append(t)

    width = max(t.shape[1] for t in cleaned)
    df = pd.concat([t.reset_index(drop=True) for t in cleaned], ignore_index=True)
    page = df.pop("_page")
    df = df.fillna("").apply(lambda col: col.astype(str).str.replace(r"\s*\n\s*", " ", regex=True).str.strip())

    names = [n or f"column_{i + 1}" for i, n in enumerate(first_row)] if header else []
    names = (names + [f"column_{i + 1}" for i in range(len(names), width - 1)])[: df.shape[1]]
    df.columns = _dedupe(names)
    df = df[~(df == "").all(axis=1)]  # fully empty rows
    if keep_page:
        df.insert(0, "page", page.loc[df.index].values)
    return df.reset_index(drop=True)


def _dedupe(names: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for n in names:
        seen[n] = seen.get(n, 0) + 1
        out.append(n if seen[n] == 1 else f"{n}_{seen[n]}")
    return out


def to_numbers(df: pd.DataFrame, columns=None, split_units: bool = True) -> pd.DataFrame:
    """Parse number columns in place of text: (1,234) -> -1234, '4,8' -> 4.8, ...

    columns=None picks every column where most non-empty cells parse as numbers.
    split_units moves a unit merged into a number cell ('subscriber 8,631') to <column>_unit.
    """
    from pdftables.numbers import parse_number, split_unit
    df = df.copy()
    if columns is None:
        columns = []
        for c in df.columns:
            if c == "page":
                continue
            cells = df[c].astype(str).str.strip()
            cells = cells[cells != ""]
            if len(cells) and cells.map(lambda v: isinstance(parse_number(split_unit(v)[1]), float)).mean() >= 0.6:
                columns.append(c)
    for c in columns:
        if split_units:
            parts = df[c].map(split_unit)
            units = parts.map(lambda p: p[0])
            if units.notna().any():
                df[f"{c}_unit"] = units
            df[c] = parts.map(lambda p: p[1])
        df[c] = df[c].map(parse_number)
    return df
