# Project updates

## Version 2: an operations analytics studio

- A dark BI layout with cyan operational charts, amber capacity figures, monospaced measures, and separate overview, capacity lab and data explorer sections.
- Validation-only precision/recall curves, holdout risk-bin counts, signed feature coefficients, and an interactive capacity comparison. Accessible chart descriptions and a threshold-value table accompany the plots.
- Fixed the report-without-database test bug: `create_app(data_dir=...)` supports a temporary dataset, and API tests generate their own database. A stale report alone still produces an explicit setup error rather than silently creating an empty database.
- **8 automated tests passed** on Python 3.13. Ruff lint/format, JavaScript syntax, pipeline regeneration and Tableau package checks pass. Desktop/phone browser checks covered chart rendering, capacity selection and provider filtering.
