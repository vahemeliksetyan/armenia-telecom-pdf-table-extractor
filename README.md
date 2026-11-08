# armenia-telecom-pdf-table-extractor

**Extract tables from PDF reports into Excel or CSV with Python, and prove that every number
came out right.** It handles the problems that break most PDF-to-Excel attempts: tables that
run across pages, header rows repeated on every page, text wrapped inside cells, `(1,234)`
accounting negatives, decimal commas, thousands separators, and units stuck to numbers. It
uses [pdfplumber](https://github.com/jsvine/pdfplumber), and can cross-check with
[Camelot](https://github.com/camelot-dev/camelot).

Built to turn **60 quarterly financial reports of Armenia's mobile operators (Viva, Ucom, Team)**
into one dataset: 3,478 numbers extracted, **3,478 confirmed** against the PDFs' own text.

```bash
pdftables extract report.pdf -o report.xlsx      # every table in the PDF -> one clean sheet
pdftables verify  report.pdf                     # 59 numbers checked: 59 found
pdftables compare report.pdf                     # pdfplumber vs Camelot: what did either miss?
```

## Do you have this problem?

You have PDFs with tables and you need the numbers in Excel, pandas or a database:

- **Financial and regulatory reports:** quarterly results, annual reports, filings to a regulator.
  Each period comes as a PDF, and you need all of them in one table.
- **Copy-paste from PDF to Excel breaks:** columns shift, rows merge, negatives in brackets become
  text, `4 385 067` won't sum.
- **Tables continue over several pages:** the header repeats on every page and ends up in your data
  as rows.
- **You tried pdfplumber, Camelot or Tabula,** and got most of the table, but you can't tell which
  cells came out wrong.
- **You need to trust the result:** a number extracted from the wrong row is worse than a missing
  one. Here, every extracted number is looked up again in the PDF's text layer.
- **Non-English documents:** the case study PDFs are in Armenian. Nothing depends on the language.

## Quick start

```bash
git clone https://github.com/vahemeliksetyan/armenia-telecom-pdf-table-extractor.git
cd armenia-telecom-pdf-table-extractor
pip install -e .                 # adds the `pdftables` command; add [camelot] for the Camelot engine

pdftables extract data/raw/viva/Viva_q4_2025.pdf -o viva.xlsx
```

```
Viva_q4_2025.pdf: 68 rows x 5 columns
-> viva.xlsx
```

Many PDFs into one table (a `source_file` column says where each row came from):

```bash
pdftables extract data/raw/*/*_q4_2025.pdf -o q4_2025_all_operators.xlsx
```

| Option | What it does |
|---|---|
| `--pages 1,3-5` | Only these pages |
| `--engine camelot` | Use Camelot instead of pdfplumber (lattice mode, for ruled tables) |
| `--no-header` | The first row is data, not column names |
| `--keep-text` | Leave cells as text; don't parse numbers |

### Check the extraction

```bash
pdftables verify data/raw/team/Team_q4_2025.pdf --out team_check.xlsx
```

The PDF's text layer is read separately from table detection. Each extracted number is then
looked up in it: **found** (same page), **elsewhere** (another page), **loose** (same digits,
different spacing) or **NOT FOUND**, which means check that cell. The report is cell by cell.

### Compare two engines

```bash
pdftables compare data/raw/viva/Viva_q1_2023.pdf
```

```
    engine  rows  columns  numbers
pdfplumber    68        4       58
   camelot    67        4       58
```

Camelot finds no table on a page that holds a single table row, so it drops that row here.
pdfplumber keeps it.

### From Python

```python
from pdftables import extract_tables, to_numbers, verify

df = extract_tables("report.pdf")          # all tables, repeated headers removed, 'page' column
df = to_numbers(df)                        # (1,234) -> -1234, '4 385 067' -> 4385067, '4,8' -> 4.8
report = verify(df, "report.pdf")          # one row per number, with its status
print(report["status"].value_counts())
```

## How the numbers are read

| In the PDF | Becomes | |
|---|---:|---|
| `4,577,372` | 4577372 | thousands commas |
| `4 385 067` | 4385067 | thousands spaces, including non-breaking |
| `(8,631)` | -8631 | accounting negative |
| `4,8` / `5 ,4` | 4.8 / 5.4 | decimal comma (1-2 digits after it) |
| `subscriber   (8,631)` | -8631, unit `subscriber` | unit merged into the number cell |
| `-`, `n/a`, empty | empty | |

## Case study: Armenian mobile operators, 2021–2025

Every operator files the same quarterly form with the Public Services Regulatory Commission of
Armenia (decision N274Ա, 1 June 2011): revenues by service, operating expenses, OIBDA, profit
before tax, capex, subscribers, ARPU, traffic. The reports are 3-page Armenian PDFs, with slightly
different layouts and wording for each operator. The full pipeline turns 60 of them
(3 operators × 20 quarters) into one English-labelled table.

### 2025 at a glance

Operating revenues, billion AMD:

| Operator | 2025 | vs 2024 |
|---|---:|---:|
| Viva | 58.03 | +5.1% |
| Ucom | 21.34 | +6.0% |
| Team | 20.92 | +5.6% |
| **Total** | **100.29** | **+5.4%** |

### Pipeline

```
data/raw/<operator>/*.pdf
  1. Extract    pdfplumber (default) or Camelot      → data/processed/
  2. Combine    one file per operator                 → data/final/intermediate/
  3. Unify      map each operator's wording to one label   (mappings/unification.xlsx)
  4. Translate  Armenian → English                          (mappings/translation.xlsx, units.xlsx)
  5. Assemble   + employee & branch counts            → data/final/final.xlsx
  6. Validate   check against the PDFs                → data/final/validation_report.xlsx
```

```bash
pip install -r requirements.txt
python run_pipeline.py                      # full run with pdfplumber
python run_pipeline.py --operator ucom      # re-extract one operator only
python run_pipeline.py --extractor both     # also run Camelot and compare the two
```

To add a quarter, drop the PDF into `data/raw/<operator>/` as `<Operator>_q<N>_<YYYY>.pdf`
(e.g. `Viva_q1_2026.pdf`) and run the pipeline again. All paths and settings are in
[`config.py`](config.py).

### Output

[`data/final/final.xlsx`](data/final/final.xlsx): one row per indicator × operator × quarter
(about 4,100 rows).

| Column | Meaning |
|---|---|
| `company` | Viva / Ucom / Team |
| `Տերեթիվ`, `year`, `quarter` | Quarter start date, year, quarter number |
| `Ինդեքս` | Line number in the report form (e.g. `1.1.3`) |
| `Values` / `Ցուցանիշ` | Indicator name in English / Armenian |
| `Main value` | Section the indicator belongs to (e.g. *Operating revenues*) |
| `Արժեք` | The reported number |
| `Measurement unit` | e.g. *thousand AMD*, *subscribers*, *AMD* |

Amounts are in **thousand AMD**. Values are stored as positive magnitudes (so expenses chart as
positive numbers). Only profit before tax, non-operating result, FX gains/losses, other operating
result, financial income and other non-operating income/expenses keep their sign (`SIGN_MATTERS`
in [`src/extraction/report_processor.py`](src/extraction/report_processor.py)). A few values the
reports leave empty are calculated by the pipeline: Ucom 9.1, 9.2, 9.5 and 9.6 (sums of their
sub-items; 9.2 is subscriber-weighted ARPU) and Viva 1 (copied from 1.1). The last rows add
employee and branch counts (2025 Q4), collected by hand from the operators' websites
([`data/external/`](data/external/)).

### Data quality

Every value in the final file is checked against the text of its source PDF
([`src/validate.py`](src/validate.py)). Of 3,553 values, 3,007 are found on their own line, 428
elsewhere in the PDF, 17 by digits only and 41 as a weak match (a small number not on its line);
60 are calculated by the pipeline and 0 are not found. The same step flags spikes, level shifts
and broken identities in the operators' own reports. See
[`data/final/anomaly_report.md`](data/final/anomaly_report.md).

Known problems **in the source reports** are listed in
[`docs/source_data_issues.md`](docs/source_data_issues.md). The most important:

- **Team, 2025 Q2 and Q4: profit before tax and Q4 capex look wrong** (depreciation entered with
  the wrong sign). Use these values with care.
- **Ucom counts broadband in active subscribers**, unlike Viva and Team, so subscriber counts and
  ARPU are not directly comparable.

## Repository layout

```
pdftables/             reusable PDF table extraction: works on any PDF
  extract.py           all tables -> one DataFrame (multi-page, repeated headers, wrapped cells)
  numbers.py           report-style number parsing
  verify.py            check every extracted number against the PDF text layer
  compare.py           pdfplumber vs Camelot
  cli.py               `pdftables extract / verify / compare`
config.py              case study: paths and settings
run_pipeline.py        case study: runs steps 1–6
src/extraction/        case study: one extractor per operator + shared report parser
src/                   case study: combine, unify, translate, assemble, validate, compare
mappings/              label unification and translation tables (editable in Excel)
data/raw/              the 60 source PDFs (public operator reports)
data/final/            final dataset, validation report, anomaly report
docs/                  source data issues
tests/                 pytest
```

## Related terms

PDF table extraction in Python, PDF to Excel, PDF to CSV, extract tables from PDF reports,
pdfplumber vs Camelot, multi-page PDF tables, parse financial statements from PDF, scrape
regulatory filings, parentheses negative numbers, decimal comma parsing, validate PDF extraction,
Armenian telecom market data, Viva, Ucom, Team Telecom Armenia.

## Disclaimer

The data comes from the operators' published quarterly reports and is shown as reported. This is
an independent analysis, not affiliated with Viva, Ucom or Team. Brand names belong to their owners.

## License

Code: [MIT](LICENSE).
