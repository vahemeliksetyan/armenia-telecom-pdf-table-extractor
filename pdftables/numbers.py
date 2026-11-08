"""Turn the number formats found in financial PDFs into floats.

    '4,577,372'   -> 4577372      thousands commas
    '4 385 067'   -> 4385067      thousands spaces (incl. non-breaking)
    '(8,631)'     -> -8631        accounting negative
    '-12.5'       -> -12.5
    '4,8' '5 ,4'  -> 4.8  5.4     decimal comma (1-2 digits after the comma)
    'subscriber   (8,631)'        unit merged into the number cell -> ('subscriber', -8631)
"""
from __future__ import annotations

import re

_EMPTY = {"", "-", "—", "–", "n/a", "N/A", "na", "NA", "nan", "None", "x"}
_UNIT_AND_NUMBER = re.compile(r"^\s*([^\d()\-]+?)\s+(\(?-?\d[\d,\.  ]*\)?)\s*$")
_DECIMAL_COMMA = re.compile(r"^\(?-?\d+,\d{1,2}\)?$")
NUMBER_TOKEN = re.compile(r"\(?-?\d{1,3}(?:(?:,|\s)\d{3})+(?:\.\d+)?\)?|\(?-?\d+(?:[.,]\d+)?\)?")


def parse_number(value, keep_sign: bool = True):
    """Float for anything that looks like a number, None for blanks, the input otherwise."""
    if value is None or isinstance(value, bool):
        return None if value is None else value
    if isinstance(value, (int, float)):
        return value if keep_sign else abs(value)
    text = str(value).strip().replace(" ", " ")
    if text in _EMPTY:
        return None
    negative = (text.startswith("(") and text.endswith(")")) or text.startswith("-")
    compact = text.replace(" ", "")
    if _DECIMAL_COMMA.fullmatch(compact):
        compact = compact.replace(",", ".")
    digits = compact.strip("()").lstrip("-").replace(",", "")
    try:
        number = float(digits)
    except ValueError:
        return value
    return -number if (negative and keep_sign) else number


def split_unit(value):
    """'subscriber (8,631)' -> ('subscriber', '(8,631)'); anything else -> (None, value)."""
    if not isinstance(value, str):
        return None, value
    m = _UNIT_AND_NUMBER.match(value)
    return (m.group(1).strip(), m.group(2)) if m else (None, value)


def numbers_in_text(text: str) -> set[float]:
    """Every number written in a block of text, parsed (rounded to 2 decimals)."""
    text = re.sub(r"(\d)\s+,(\d)", r"\1,\2", text)  # '5 ,4' -> '5,4'
    found = set()
    for token in NUMBER_TOKEN.findall(text):
        n = parse_number(token, keep_sign=False)
        if isinstance(n, float):
            found.add(round(n, 2))
    return found
