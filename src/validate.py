"""
Step 6 — Validate: check data/final/final.xlsx against the source PDFs.

Checks (one sheet each in the report):
  pdf_match     every value is looked up in the PDF's own text layer (read
                independently of the table extraction):
                  line   – found on the line of its index (e.g. '1.1.3 ...')
                  file   – found elsewhere in the same PDF
                  loose  – digits found in the PDF once spaces/commas are ignored
                  CHECK  – a small number that is in the PDF, but not on its own line
                  calculated – not in the PDF, but the pipeline computes it on purpose
                  NOT FOUND  – not in the PDF: review
  sources       duplicate PDFs, and the period in the PDF title vs the file name
  totals        revenue/expense sections: parent vs sum of its children (1.1 vs 1.1.1 + ...)
  anomalies     each indicator over time: spikes, x10/x1000 errors, zeros, level shifts (not sections 6–8)
  consistency   ARPU vs revenue/subscribers; subscribers = previous + new - churn
  completeness  indexes missing in a quarter, or a quarter identical to another one

Writes data/final/validation_report.xlsx and a readable summary, data/final/anomaly_report.md.
Run alone:   python src/validate.py [--extractor camelot]
"""
import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pdfplumber

import config

# Values the extractors compute instead of reading (see src/extraction/extract_*.py)
CALCULATED = {
    "Ucom": {"9.1", "9.2", "9.5", "9.6"},
    "Viva": {"1"},
}

INDEX_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\)?(?=\s|$)")
NUMBER_RE = re.compile(r"\(?-?\d{1,3}(?:(?:,|\s)\d{3})+(?:\.\d+)?\)?|\(?-?\d+(?:[.,]\d+)?\)?")
PERIOD_RE = re.compile(r"(20\d\d)\s*(?:թ\.?|թվականի)?\s*(1-ին|2-րդ|3-րդ|4-րդ)\s*եռամսյակ")
QUARTER_WORDS = {"1-ին": 1, "2-րդ": 2, "3-րդ": 3, "4-րդ": 4}

JUMP_RATIO = 2.5          # flag values > 2.5x or < 1/2.5x the operator's median for that index
TOTALS_TOLERANCE = 0.01   # children may differ from the parent by 1% (rounding)

# Only these sections are true sums of their sub-items. Section 9 holds averages and
# overlapping 'of which' rows; section 6 mixes income and expenses.
TOTALS_SECTIONS = ("1", "2")
# Sections that swing a lot by nature (FX, financial result, profit, capex) — no jump check
VOLATILE_SECTIONS = ("6", "7", "8")
ARPU_TOLERANCE = 0.12     # ARPU may differ 12% from the operator's usual ARPU/(revenue/subscribers) ratio
BALANCE_TOLERANCE = 0.01  # subscriber balance may be off by 1%
SMALL_VALUE = 1000        # small indexed values found only elsewhere in the PDF are too weak a match


# ── PDF text ─────────────────────────────────────────────────────────────────
def parse_number(token):
    """'4,577,372' → 4577372, '4 385 067' → 4385067, '4,8' / '5 ,4' → 4.8 / 5.4."""
    t = token.strip("()-").replace(" ", " ")
    compact = t.replace(" ", "")
    if re.fullmatch(r"\d+,\d{1,2}", compact):
        return float(compact.replace(",", "."))
    try:
        return float(compact.replace(",", ""))
    except ValueError:
        return None


def numbers_in(text):
    return {round(v, 2) for v in map(parse_number, NUMBER_RE.findall(text)) if v is not None}


class PdfText:
    """Text layer of one PDF, split into lines, with the numbers on each line."""

    def __init__(self, path):
        with pdfplumber.open(path) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        text = re.sub(r"(\d)\s+,(\d)", r"\1,\2", text)          # '5 ,4' → '5,4'
        self.text = text
        self.lines = text.splitlines()
        self.all_numbers = numbers_in(text)
        self.digits = re.sub(r"[\s,]", "", text)
        first_page = re.sub(r"\s+", " ", text[:1500])
        m = PERIOD_RE.search(first_page)
        self.period = (int(m.group(1)), QUARTER_WORDS[m.group(2)]) if m else None

    def numbers_near_index(self, idx, lookahead=3):
        """Numbers on the line that starts with idx and the next few lines (wrapped labels)."""
        found = set()
        for i, line in enumerate(self.lines):
            m = INDEX_RE.match(line)
            if m and m.group(1) == idx:
                found |= numbers_in(line[m.end():])
                for nxt in self.lines[i + 1 : i + 1 + lookahead]:
                    if INDEX_RE.match(nxt):
                        break
                    found |= numbers_in(nxt)
        return found


def find_pdf(company, quarter, year):
    matches = sorted(config.raw_dir(company).glob(f"*_q{int(quarter)}_{int(year)}.pdf"))
    return matches[0] if matches else None


# ── Checks ───────────────────────────────────────────────────────────────────
def check_sources():
    rows, seen = [], {}
    for company in config.OPERATORS:
        for pdf in sorted(config.raw_dir(company).glob("*.pdf")):
            digest = hashlib.md5(pdf.read_bytes()).hexdigest()
            m = re.search(r"q([1-4])_(\d{4})", pdf.name.lower())
            name_period = (int(m.group(2)), int(m.group(1))) if m else None
            period = PdfText(pdf).period
            if digest in seen:
                status, note = "DUPLICATE", f"same file as {seen[digest]}"
            elif period is None:
                status, note = "unverified", "no readable period in the PDF title — check by eye"
            elif period != name_period:
                status, note = "WRONG PERIOD", f"PDF title says {period[0]} Q{period[1]}"
            else:
                status, note = "ok", ""
            seen.setdefault(digest, pdf.name)
            rows.append({"company": company, "file": pdf.name, "status": status, "note": note})
    return pd.DataFrame(rows)


def check_pdf_match(df):
    rows, cache = [], {}
    for _, r in df.iterrows():
        value = r["Արժեք"]
        if pd.isna(value):
            continue
        pdf = find_pdf(r["company"], r["quarter"], r["year"])
        if pdf is None:
            status = "NO PDF"
        else:
            if pdf not in cache:
                cache[pdf] = PdfText(pdf)
            text = cache[pdf]
            idx = "" if pd.isna(r["Ինդեքս"]) else str(r["Ինդեքս"]).strip()
            v = round(abs(float(value)), 2)
            digits = f"{abs(value):.0f}" if float(value).is_integer() else ""
            if idx and v in text.numbers_near_index(idx):
                status = "line"
            elif v in text.all_numbers and (not idx or v >= SMALL_VALUE):
                status = "file"
            elif v in text.all_numbers:
                status = "CHECK"     # small number, appears in the PDF but not on its own line
            elif len(digits) >= 4 and digits in text.digits:
                status = "loose"
            elif idx in CALCULATED.get(r["company"], set()):
                status = "calculated"
            else:
                status = "NOT FOUND"
        rows.append({
            "status": status, "company": r["company"], "year": r["year"], "quarter": r["quarter"],
            "Ինդեքս": r["Ինդեքս"], "label": r["Values"], "value": value,
            "pdf": pdf.name if pdf else None, "final_row": r.name + 2,
        })
    return pd.DataFrame(rows)


def check_totals(df):
    rows = []
    idx = df["Ինդեքս"].astype(str).str.strip()
    for (company, date), g in df[idx.str.fullmatch(r"\d+(\.\d+)*")].groupby(["company", "Տերեթիվ"]):
        values = dict(zip(g["Ինդեքս"].astype(str).str.strip(), g["Արժեք"]))
        for parent, pv in values.items():
            if parent.split(".")[0] not in TOTALS_SECTIONS:
                continue
            children = [v for k, v in values.items() if re.fullmatch(re.escape(parent) + r"\.\d+", k)]
            children = [c for c in children if pd.notna(c)]
            if len(children) < 2 or pd.isna(pv):
                continue
            total = sum(abs(c) for c in children)
            diff = abs(pv) - total
            if abs(diff) > TOTALS_TOLERANCE * max(abs(pv), 1):
                rows.append({"company": company, "date": date, "Ինդեքս": parent,
                             "label": g.loc[g["Ինդեքս"].astype(str).str.strip() == parent, "Values"].iloc[0],
                             "parent": pv, "sum_of_children": total, "difference": diff,
                             "n_children": len(children)})
    return pd.DataFrame(rows, columns=["company", "date", "Ինդեքս", "label", "parent",
                                       "sum_of_children", "difference", "n_children"])


def _series(df):
    """One row per company / quarter / index (first occurrence), sorted by date."""
    d = df[df["Ինդեքս"].notna() & df["Արժեք"].notna()].copy()
    d["Ինդեքս"] = d["Ինդեքս"].astype(str).str.strip()
    d = d.drop_duplicates(["company", "Տերեթիվ", "Ինդեքս"])
    return d.sort_values(["company", "Ինդեքս", "Տերեթիվ"])


def _far(a, b):
    """True when a and b differ by more than JUMP_RATIO times (both non-zero)."""
    a, b = abs(a), abs(b)
    return a > 0 and b > 0 and max(a, b) / min(a, b) > JUMP_RATIO


def _power_of_ten(ratio):
    """10, 100, 1000 (or 1/10 ...) within 10% — typical decimal / unit mistakes."""
    for k in (1, 2, 3):
        for target in (10 ** k, 10 ** -k):
            if abs(ratio / target - 1) < 0.1:
                return f"x{10 ** k}" if target > 1 else f"/{10 ** k}"
    return None


def check_anomalies(df):
    """
    Look at each indicator over time, per operator:
      HIGH    spike      — jumps away from both neighbours, which agree with each other
      HIGH    x10 / /10  — about 10, 100 or 1000 times the usual level (decimal or unit error)
      HIGH    zero       — 0 between two non-zero quarters (missing value saved as 0?)
      LOW     level shift — jumps and stays at the new level (often a real business change)
    """
    rows = []
    d = _series(df)
    d = d[~d["Ինդեքս"].str.split(".").str[0].isin(VOLATILE_SECTIONS)]
    for (company, idx), g in d.groupby(["company", "Ինդեքս"]):
        values = g["Արժեք"].tolist()
        dates = g["Տերեթիվ"].tolist()
        nonzero = [abs(v) for v in values if v != 0]
        median = pd.Series(nonzero).median() if nonzero else 0
        last_spike = -2
        for i, v in enumerate(values):
            prev = values[i - 1] if i > 0 else None
            nxt = values[i + 1] if i + 1 < len(values) else None
            kind = None
            if v == 0 and prev and nxt and min(abs(prev), abs(nxt)) >= 1:   # ignore 0 vs 0.1 rounding
                kind, priority = "zero between non-zero quarters", "HIGH"
            elif median and v != 0 and _power_of_ten(abs(v) / median):
                kind, priority = f"{_power_of_ten(abs(v) / median)} the usual level", "HIGH"
            elif prev is not None and nxt is not None and _far(v, prev) and _far(v, nxt) and not _far(prev, nxt):
                kind, priority = "spike (jumps and comes back)", "HIGH"
            elif prev is not None and _far(v, prev) and (nxt is None or not _far(v, nxt)) and last_spike != i - 1:
                kind, priority = "level shift (new level stays)", "LOW"
            if kind and kind.startswith("spike"):
                last_spike = i
            if kind:
                rows.append({"priority": priority, "type": kind, "company": company, "date": dates[i],
                             "Ինդեքս": idx, "label": g["Values"].iloc[i], "value": v,
                             "previous": prev, "next": nxt, "usual (median)": median})
    out = pd.DataFrame(rows, columns=["priority", "type", "company", "date", "Ինդեքս", "label",
                                      "value", "previous", "next", "usual (median)"])
    return out.sort_values(["priority", "company", "Ինդեքս", "date"])


def check_consistency(df):
    """
    Cross-check related indicators of the same operator and quarter:
      ARPU      9.2 vs revenue 1.1 / average subscribers 9.1 / 3 months — the ratio is
                stable per operator, so a quarter far from that operator's usual ratio is suspect
      balance   subscribers 9.1 = previous 9.1 + new activations 9.5 - churn 9.6
    """
    d = _series(df)
    p = d[d["Ինդեքս"].isin(["1.1", "9.1", "9.2", "9.5", "9.6"])] \
        .pivot_table(index=["company", "Տերեթիվ"], columns="Ինդեքս", values="Արժեք")
    rows = []
    for company, g in p.groupby(level=0):
        g = g.droplevel(0).sort_index()
        avg_subs = ((g["9.1"] + g["9.1"].shift()) / 2).fillna(g["9.1"])
        implied = g["1.1"] * 1000 / avg_subs / 3          # revenue is in thousand AMD
        ratio = g["9.2"] / implied
        usual = ratio.median()
        for date, r in ratio.items():
            if pd.notna(r) and abs(r / usual - 1) > ARPU_TOLERANCE:
                rows.append({"check": "ARPU vs revenue/subscribers", "company": company, "date": date,
                             "actual": g.at[date, "9.2"], "expected": implied[date] * usual,
                             "difference %": round((r / usual - 1) * 100, 1)})
        expected = g["9.1"].shift() + g["9.5"].abs() - g["9.6"].abs()
        for date, e in expected.items():
            a = g.at[date, "9.1"]
            if pd.notna(e) and e and abs(a / e - 1) > BALANCE_TOLERANCE:
                rows.append({"check": "subscriber balance (prev + new - churn)", "company": company,
                             "date": date, "actual": a, "expected": e,
                             "difference %": round((a / e - 1) * 100, 1)})
    return pd.DataFrame(rows, columns=["check", "company", "date", "actual", "expected", "difference %"])


def check_completeness(df):
    rows = []
    d = df[df["Ինդեքս"].notna()].copy()
    d["Ինդեքս"] = d["Ինդեքս"].astype(str).str.strip()
    for company, g in d.groupby("company"):
        per_q = {date: set(x["Ինդեքս"]) for date, x in g.groupby("Տերեթիվ")}
        usual = set.intersection(*per_q.values()) if per_q else set()
        everywhere = pd.Series([i for s in per_q.values() for i in s]).value_counts()
        common = set(everywhere[everywhere >= len(per_q) * 0.75].index)
        for date, s in sorted(per_q.items()):
            missing = sorted(common - s)
            if missing:
                rows.append({"company": company, "date": date, "issue": "missing indexes",
                             "detail": ", ".join(missing)})
        vals = {date: tuple(x["Արժեք"].fillna(-1).round(2)) for date, x in g.groupby("Տերեթիվ")}
        dates = sorted(vals)
        for a, b in zip(dates, dates[1:]):
            if len(vals[a]) == len(vals[b]) and vals[a] == vals[b]:
                rows.append({"company": company, "date": b, "issue": "identical to previous quarter",
                             "detail": f"all values equal {a}"})
    return pd.DataFrame(rows, columns=["company", "date", "issue", "detail"])


# ── Text report ──────────────────────────────────────────────────────────────
BARS = "▁▂▃▄▅▆▇█"


def quarter_label(date):
    d = pd.Timestamp(date)
    return f"{d.year} Q{(d.month - 1) // 3 + 1}"


def fmt(v):
    if v is None or pd.isna(v):
        return "–"
    v = float(v)
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}".rstrip("0").rstrip(".")


def sparkline(values, dates, mark_date):
    """One bar per quarter, a space between years, and a ^ under the marked quarter."""
    nums = [abs(v) for v in values if pd.notna(v)]
    lo, hi = (min(nums), max(nums)) if nums else (0, 0)
    bars, marker, year = "", "", None
    for v, d in zip(values, dates):
        y = pd.Timestamp(d).year
        if year is not None and y != year:
            bars, marker = bars + " ", marker + " "
        year = y
        bars += "·" if pd.isna(v) else BARS[int((abs(v) - lo) / (hi - lo) * 7) if hi > lo else 3]
        marker += "^" if d == mark_date else " "
    first, last = quarter_label(dates[0]), quarter_label(dates[-1])
    return f"{first}  {bars}  {last}\n{' ' * (len(first) + 2)}{marker.rstrip()}"


def change(value, other):
    if other is None or pd.isna(other) or other == 0:
        return ""
    return f" ({(abs(value) / abs(other) - 1) * 100:+.0f}%)"


def write_text_report(df, summary, anomalies, consistency, match, sources, extractor):
    series = _series(df)
    pdf_status = {
        (r.company, int(r.year), int(r.quarter), str(r.Ինդեքս).strip()): r.status
        for r in match.itertuples() if pd.notna(r.Ինդեքս)
    }
    pdf_words = {"line": "yes, on its own line", "file": "yes", "loose": "yes (digits match)",
                 "CHECK": "weak match — check", "calculated": "no — calculated by the pipeline",
                 "NOT FOUND": "NOT FOUND in the PDF"}

    def chart(company, idx, date):
        g = series[(series["company"] == company) & (series["Ինդեքս"] == idx)]
        return sparkline(g["Արժեք"].tolist(), g["Տերեթիվ"].tolist(), date)

    lines = [
        "# Data anomaly report",
        "",
        f"Generated {pd.Timestamp.now():%Y-%m-%d %H:%M} from `{config.final_file(extractor).relative_to(config.ROOT)}`. "
        "Charts show the indicator for that operator, one bar per quarter (taller = larger value); "
        "`^` marks the flagged quarter.",
        "",
        "## Summary",
        "",
        "```",
        summary.to_string(index=False),
        "```",
    ]

    bad_sources = sources[sources["status"].isin(["DUPLICATE", "WRONG PERIOD"])]
    not_found = match[match["status"].isin(["NOT FOUND", "NO PDF"])]
    if len(bad_sources) or len(not_found):
        lines += ["", "## Data errors (fix before analysis)", ""]
        for r in bad_sources.itertuples():
            lines.append(f"- **{r.file}** — {r.status}: {r.note}")
        for r in not_found.itertuples():
            lines.append(f"- **{r.company} {r.year} Q{r.quarter}, {r.Ինդեքս} {r.label}** = {fmt(r.value)} "
                         f"is not in {r.pdf}")

    high = anomalies[anomalies["priority"] == "HIGH"]
    lines += ["", f"## Major anomalies ({len(high)})", "",
              "Values far from both neighbouring quarters, x10/x1000 the usual level, or 0 between normal "
              "quarters. If the value is in the PDF, the operator reported it that way — decide whether "
              "it is a real event or a reporting error before using it.", ""]
    if high.empty:
        lines.append("None.")
    for i, r in enumerate(high.itertuples(), 1):
        d = pd.Timestamp(r.date)
        found = pdf_words.get(pdf_status.get((r.company, d.year, (d.month - 1) // 3 + 1, r.Ինդեքս)), "–")
        lines += [
            f"### {i}. {r.company} — {r.Ինդեքս} {r.label} — {quarter_label(r.date)}",
            "",
            f"- **Type:** {r.type}",
            f"- **Value:** {fmt(r.value)} · previous quarter {fmt(r.previous)}{change(r.value, r.previous)} · "
            f"next quarter {fmt(r.next)}{change(r.value, r.next)} · usual {fmt(r._10)}",
            f"- **In the PDF:** {found}",
            "",
            "```",
            chart(r.company, r.Ինդեքս, r.date),
            "```",
            "",
        ]

    lines += ["", f"## Consistency failures ({len(consistency)})", "",
              "Related indicators that should agree: ARPU vs revenue / subscribers, and "
              "subscribers = previous quarter + new activations − churn.", ""]
    if consistency.empty:
        lines.append("None.")
    else:
        lines += ["| Check | Operator | Quarter | Actual | Expected | Difference |", "|---|---|---|---|---|---|"]
        for r in consistency.itertuples():
            lines.append(f"| {r.check} | {r.company} | {quarter_label(r.date)} | {fmt(r.actual)} | "
                         f"{fmt(r.expected)} | {r._6:+.1f}% |")

    low = anomalies[anomalies["priority"] == "LOW"]
    lines += ["", f"## Level shifts ({len(low)})", "",
              "The indicator moved to a new level and stayed there — usually a real change "
              "(new tariff, reclassified costs), listed for context.", ""]
    if low.empty:
        lines.append("None.")
    else:
        lines += ["| Operator | Indicator | Quarter | Before | After |", "|---|---|---|---|---|"]
        for r in low.itertuples():
            lines.append(f"| {r.company} | {r.Ինդեքս} {r.label} | {quarter_label(r.date)} | "
                         f"{fmt(r.previous)} | {fmt(r.value)}{change(r.value, r.previous)} |")

    out = config.anomaly_report_file(extractor)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ── Main ─────────────────────────────────────────────────────────────────────
def run(extractor=config.DEFAULT_EXTRACTOR):
    df = pd.read_excel(config.final_file(extractor))
    df = df[df["company"].isin(config.OPERATORS) & (df["Ինդեքս"].astype(str) != "EMP")]
    df = df[df["source_file"].astype(str).str.lower().str.endswith(".pdf")]   # PDF rows only

    print("Checking source PDFs ...")
    sources = check_sources()
    print("Matching values against PDF text ...")
    match = check_pdf_match(df)
    totals = check_totals(df)
    anomalies = check_anomalies(df)
    consistency = check_consistency(df)
    completeness = check_completeness(df)

    counts = match["status"].value_counts()
    summary = pd.DataFrame([
        ("Values checked",                           len(match)),
        ("  found on the index line",                counts.get("line", 0)),
        ("  found elsewhere in the PDF",             counts.get("file", 0)),
        ("  found loosely (digits only)",            counts.get("loose", 0)),
        ("  calculated by the pipeline (expected)",  counts.get("calculated", 0)),
        ("  weak match (small number not on its line)", counts.get("CHECK", 0)),
        ("  NOT FOUND in PDF — review",              counts.get("NOT FOUND", 0) + counts.get("NO PDF", 0)),
        ("Source PDFs with problems",                (sources["status"].isin(["DUPLICATE", "WRONG PERIOD"])).sum()),
        ("Source PDFs to check by eye",              (sources["status"] == "unverified").sum()),
        ("Totals that don't add up",                 len(totals)),
        ("Anomalies — HIGH (spike, x10, zero)",      (anomalies["priority"] == "HIGH").sum()),
        ("Anomalies — LOW (level shifts)",           (anomalies["priority"] == "LOW").sum()),
        ("Consistency checks failed",                len(consistency)),
        ("Completeness issues",                      len(completeness)),
    ], columns=["check", "count"])

    out = config.validation_file(extractor)
    with pd.ExcelWriter(out) as writer:
        summary.to_excel(writer, sheet_name="summary", index=False)
        problems = match[~match["status"].isin(["line", "file", "loose"])]
        problems.to_excel(writer, sheet_name="pdf_match_review", index=False)
        match.to_excel(writer, sheet_name="pdf_match_all", index=False)
        sources.to_excel(writer, sheet_name="sources", index=False)
        totals.to_excel(writer, sheet_name="totals", index=False)
        anomalies.to_excel(writer, sheet_name="anomalies", index=False)
        consistency.to_excel(writer, sheet_name="consistency", index=False)
        completeness.to_excel(writer, sheet_name="completeness", index=False)

    report = write_text_report(df, summary, anomalies, consistency, match, sources, extractor)

    print(summary.to_string(index=False))
    print(f"\nSaved → {out.relative_to(config.ROOT)}")
    print(f"Saved → {report.relative_to(config.ROOT)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--extractor", choices=config.EXTRACTORS, default=config.DEFAULT_EXTRACTOR)
    run(parser.parse_args().extractor)
