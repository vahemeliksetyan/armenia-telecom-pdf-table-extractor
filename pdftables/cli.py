"""Extract tables from PDF files into Excel/CSV, and check the result against the PDF.

    pdftables extract report.pdf -o report.xlsx            # all tables, one sheet, numbers parsed
    pdftables extract reports/*.pdf -o all.xlsx            # many PDFs into one table (+ source_file)
    pdftables verify  report.pdf                           # is every extracted number in the PDF?
    pdftables compare report.pdf                           # pdfplumber vs Camelot
"""
import argparse
from pathlib import Path

import pandas as pd

from pdftables.compare import compare_engines
from pdftables.extract import ENGINES, extract_tables, to_numbers
from pdftables.verify import summary, verify


def _extract(pdf: Path, args) -> pd.DataFrame:
    df = extract_tables(pdf, engine=args.engine, pages=args.pages, header=not args.no_header)
    if not args.keep_text:
        df = to_numbers(df)
    return df


def _write(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        df.to_excel(path, index=False)
    else:
        df.to_csv(path, index=False)


def cmd_extract(args) -> None:
    frames = []
    for pdf in args.pdf:
        df = _extract(pdf, args)
        print(f"{pdf.name}: {len(df)} rows x {df.shape[1]} columns")
        if len(args.pdf) > 1:
            df.insert(0, "source_file", pdf.name)
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    target = args.out or args.pdf[0].with_suffix(".xlsx")
    _write(out, target)
    print(f"-> {target}")


def cmd_verify(args) -> None:
    for pdf in args.pdf:
        df = _extract(pdf, args)
        report = verify(df, pdf)
        print(f"{pdf.name}: {summary(report)}")
        bad = report[report["status"] == "NOT FOUND"]
        if len(bad):
            print(bad.head(20).to_string(index=False))
        if args.out:
            _write(report, args.out if len(args.pdf) == 1 else args.out.with_name(f"{pdf.stem}_{args.out.name}"))


def cmd_compare(args) -> None:
    for pdf in args.pdf:
        table, diffs = compare_engines(pdf, pages=args.pages)
        print(f"{pdf.name}\n{table.to_string(index=False)}")
        print("numbers found by both engines" if diffs.empty else diffs.head(30).to_string(index=False))


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="pdftables", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("pdf", type=Path, nargs="+", help="PDF file(s)")
    common.add_argument("--pages", help="e.g. 1,3-5 (default: all)")

    opts = argparse.ArgumentParser(add_help=False)
    opts.add_argument("--engine", choices=ENGINES, default="pdfplumber")
    opts.add_argument("--no-header", action="store_true", help="first row is data, not column names")
    opts.add_argument("--keep-text", action="store_true", help="do not parse numbers")

    e = sub.add_parser("extract", parents=[common, opts], help="PDF tables -> Excel/CSV")
    e.add_argument("--out", "-o", type=Path, help="output .xlsx or .csv (default: <pdf>.xlsx)")
    e.set_defaults(func=cmd_extract)

    v = sub.add_parser("verify", parents=[common, opts], help="check extracted numbers against the PDF text")
    v.add_argument("--out", "-o", type=Path, help="write the cell-by-cell report")
    v.set_defaults(func=cmd_verify)

    c = sub.add_parser("compare", parents=[common], help="pdfplumber vs Camelot on the same PDF")
    c.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
