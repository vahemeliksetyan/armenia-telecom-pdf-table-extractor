# Armenian mobile operators — competitive analysis (2021–2025)

Quarterly financial and operating indicators of Armenia's three mobile operators —
**Viva**, **Ucom** and **Team** (Telecom Armenia) — extracted from their official reports
into one comparable, English-labelled dataset.

Every operator files the same quarterly report form (approved by the Public Services
Regulatory Commission of Armenia, decision N274Ա of 1 June 2011): revenues by service,
operating expenses, OIBDA, profit before tax, capex, subscribers, ARPU, traffic and more.
The reports are 3-page Armenian PDFs with slightly different layouts and wording per
operator. This project turns 60 of them (3 operators × 20 quarters, 2021 Q1 – 2025 Q4)
into a single table.

## 2025 at a glance

Operating revenues, billion AMD:

| Operator | 2025 | vs 2024 |
|---|---:|---:|
| Viva | 58.03 | +5.1% |
| Ucom | 21.34 | +6.0% |
| Team | 20.92 | +5.6% |
| **Total** | **100.29** | **+5.4%** |

## Output

[`data/final/final.xlsx`](data/final/final.xlsx) — one row per indicator × operator × quarter
(about 4,100 rows). Main columns:

| Column | Meaning |
|---|---|
| `company` | Viva / Ucom / Team |
| `Տերեթիվ`, `year`, `quarter` | Quarter start date, year, quarter number |
| `Ինդեքս` | Line number in the report form (e.g. `1.1.3`) |
| `Values` / `Ցուցանիշ` | Indicator name in English / Armenian |
| `Main value` | Section the indicator belongs to (e.g. *Operating revenues*) |
| `Արժեք` | The reported number |
| `Measurement unit` | e.g. *thousand AMD*, *subscribers*, *AMD* |

Amounts are in **thousand AMD**. Values are stored as positive magnitudes (so expenses
chart as positive numbers); only profit before tax, non-operating result, FX gains/losses,
other operating result, financial income and other non-operating income/expenses keep
their sign (`SIGN_MATTERS` in [`src/extraction/report_processor.py`](src/extraction/report_processor.py)).
A few values the reports leave empty are calculated by the pipeline: Ucom 9.1, 9.2, 9.5
and 9.6 (sums of their sub-items; 9.2 is subscriber-weighted ARPU) and Viva 1 (copied from 1.1).
The last rows add employee and branch counts (2025 Q4), collected by hand from the
operators' websites ([`data/external/`](data/external/)).

## Data quality

Every value in the final file is checked against the text of its source PDF
([`src/validate.py`](src/validate.py)). Of 3,553 values, 3,007 are found on their own line,
428 elsewhere in the PDF, 17 by digits only and 41 as a weak match (small number not on its
line); 60 are calculated by the pipeline and 0 are not found.
The same step flags spikes, level shifts and broken identities in the operators' own
reports — see [`data/final/anomaly_report.md`](data/final/anomaly_report.md).

Known problems **in the source reports** are listed in
[`docs/source_data_issues.md`](docs/source_data_issues.md). The most important:

- **Team, 2025 Q2 and Q4 — profit before tax and Q4 capex look wrong** (depreciation
  entered with the wrong sign). Use these values with care.
- **Ucom counts broadband in active subscribers**, unlike Viva and Team, so subscriber
  counts and ARPU are not directly comparable.

## How it works

```
data/raw/<operator>/*.pdf
  1. Extract    pdfplumber (default) or Camelot      → data/processed/
  2. Combine    one file per operator                 → data/final/intermediate/
  3. Unify      map each operator's wording to one label   (mappings/unification.xlsx)
  4. Translate  Armenian → English                          (mappings/translation.xlsx, units.xlsx)
  5. Assemble   + employee & branch counts            → data/final/final.xlsx
  6. Validate   check against the PDFs                → data/final/validation_report.xlsx
```

All paths and settings are in [`config.py`](config.py).

## Run it

Python 3.10+.

```bash
pip install -r requirements.txt
python run_pipeline.py                      # full run with pdfplumber
python run_pipeline.py --operator ucom      # re-extract one operator only
python run_pipeline.py --extractor both     # also run Camelot and compare the two
```

To add a quarter, drop the PDF into `data/raw/<operator>/` as `<Operator>_q<N>_<YYYY>.pdf`
(e.g. `Viva_q1_2026.pdf`) and run the pipeline again.

## Repository layout

```
config.py              paths and settings
run_pipeline.py        runs steps 1–6
src/extraction/        one extractor per operator + shared PDF table parser
src/                   combine, unify, translate, assemble, validate, compare
mappings/              label unification and translation tables (editable in Excel)
data/raw/              source PDFs
data/external/         hand-collected employee and branch counts
data/final/            final dataset, validation report, anomaly report
docs/                  source data issues
```

## Disclaimer

The data comes from the operators' published quarterly reports and is shown as reported.
This is an independent analysis, not affiliated with Viva, Ucom or Team. Brand
names belong to their owners.

## License

Code: [MIT](LICENSE).
