import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from pdftables import extract_tables, parse_number, split_unit, to_numbers, verify
from pdftables.numbers import numbers_in_text

ROOT = Path(__file__).resolve().parents[1]
VIVA = ROOT / "data" / "raw" / "viva" / "Viva_q4_2025.pdf"
TEAM = ROOT / "data" / "raw" / "team" / "Team_q4_2025.pdf"


@pytest.mark.parametrize("raw, expected", [
    ("4,577,372", 4577372.0),
    ("4 385 067", 4385067.0),
    ("4 385 067", 4385067.0),
    ("(8,631)", -8631.0),
    ("-12.5", -12.5),
    ("4,8", 4.8),
    ("5 ,4", 5.4),
    ("", None),
    ("-", None),
    ("n/a", None),
])
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


def test_parse_number_keeps_text_and_drops_sign_on_request():
    assert parse_number("subscribers") == "subscribers"
    assert parse_number("(8,631)", keep_sign=False) == 8631.0


def test_split_unit():
    assert split_unit("subscriber   (8,631)") == ("subscriber", "(8,631)")
    assert split_unit("1,234") == (None, "1,234")


def test_numbers_in_text():
    assert numbers_in_text("Revenue 4,577,372 and (8,631); ARPU 5 ,4") >= {4577372.0, 8631.0, 5.4}


def test_extract_multi_page_table():
    df = extract_tables(VIVA)
    assert {"page"} <= set(df.columns)
    assert df["page"].nunique() > 1             # table continues across pages
    header = df.columns[2]
    assert (df[header] != header).all()         # repeated page header rows were removed
    assert not df.apply(lambda c: c.astype(str).str.contains("\n")).any().any()  # wrapped text joined


@pytest.mark.parametrize("pdf", [VIVA, TEAM])
def test_every_number_is_in_the_pdf(pdf):
    report = verify(to_numbers(extract_tables(pdf)), pdf)
    assert len(report) > 50
    assert (report["status"] != "NOT FOUND").all()


def test_cli_extract(tmp_path):
    out = tmp_path / "viva.csv"
    subprocess.run([sys.executable, "-m", "pdftables", "extract", str(VIVA), "-o", str(out)],
                   check=True, cwd=ROOT, capture_output=True)
    df = pd.read_csv(out)
    assert len(df) > 50 and "page" in df.columns
