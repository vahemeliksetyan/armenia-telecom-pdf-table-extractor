"""
Step 3 — Unify: give the same indicator the same label across operators.

Uses mappings/unification.xlsx:
  row 0: title (ignored)
  row 1: headers  Viva | Ucom | Team | To be
  rows 2+: each operator's label → unified label ("To be")

Matching ignores extra spaces, letter case and Armenian ligatures (ﬔ, ﬕ),
so e.g. '(SMS և MMS)' matches '(sms և mms)'. Output labels are written
exactly as in the "To be" column.

Writes data/final/intermediate/all_combined_unified.xlsx and unique_labels.xlsx.
Run alone:   python src/unify.py [--extractor camelot]
"""
import argparse
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

import config

LABEL_COL = "Արժեք"


def _norm(x):
    """Collapse whitespace."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return re.sub(r"\s+", " ", str(x)).strip()


def _key(x):
    """Lookup key: also ignore letter case and Armenian ligatures (ﬔ -> մե, ﬕ -> մի)."""
    return unicodedata.normalize("NFKC", _norm(x)).casefold()


def load_unification_maps(path):
    """Returns dict maps[company][key(old label)] = unified label."""
    raw = pd.read_excel(path, header=None)

    headers = raw.iloc[1].tolist()      # ['Viva','Ucom','Team','To be']
    uni = raw.iloc[2:].copy()
    uni.columns = headers

    unified_col = headers[-1]           # "To be"
    maps = {}
    for company in headers[:-1]:
        sub = uni[[company, unified_col]].dropna(subset=[company, unified_col])
        maps[company] = {_key(k): _norm(v) for k, v in zip(sub[company], sub[unified_col])}
    return maps


def unify_column(df, company, maps, col):
    """Replace df[col] using the company's map; unmatched labels stay as they are."""
    if col not in df.columns:
        raise ValueError(f"Column '{col}' not found. Columns: {list(df.columns)}")
    mp = maps.get(company, {})
    df[col] = df[col].map(lambda x: mp.get(_key(x), x))
    return df


def run(extractor=config.DEFAULT_EXTRACTOR):
    maps = load_unification_maps(config.UNIFICATION_MAP)

    dfs = []
    for company in config.OPERATORS:
        filepath = config.combined_file(company, extractor)
        df = pd.read_excel(filepath)
        df = unify_column(df, company, maps, LABEL_COL)
        df["company"] = company
        dfs.append(df)

    final_df = pd.concat(dfs, ignore_index=True)

    out = config.unified_file(extractor)
    final_df.to_excel(out, index=False)
    print("Saved:", out.relative_to(config.ROOT))

    unique_df = pd.DataFrame({LABEL_COL: final_df[LABEL_COL].dropna().unique()})
    out = config.unique_labels_file(extractor)
    unique_df.to_excel(out, index=False)
    print("Saved unique labels:", out.relative_to(config.ROOT))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=config.EXTRACTORS, default=config.DEFAULT_EXTRACTOR)
    run(parser.parse_args().extractor)
