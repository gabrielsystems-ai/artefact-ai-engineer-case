# Emporio Support Agent

This project aims to build a small Python customer-service agent for Emporio da Musica, a fictional musical instrument store, using supplied store data and policies for the Artefact AI Engineer challenge.

## Development status

Implementation is in progress. Deterministic CSV loading and structural validation are available through `emporio_support_agent.data.load_store_data(data_dir)`. Exact catalog lookup/filtering, product availability and unit-price quotes are also implemented. The customer-service agent is not implemented yet.

The loader returns frozen records and tuple collections, preserving source money as `Decimal`, dates and independent product descriptions/specifications. It validates required columns, primary IDs and cross-table references. It accepts `products.csv`-style names or the original `desafio_tecnico_ai_eng - products.csv` naming convention for all six tables, and rejects ambiguous copies. Diagnostic row numbers count CSV records, including the header as row 1.

`emporio_support_agent.catalog` preserves source order and requires active status plus sufficient stock for availability. `emporio_support_agent.pricing` applies one active promotion or the standard 5% PIX discount, never both. Multiple active promotions raise a conflict. Final prices use `Decimal` with cent rounding via `ROUND_HALF_UP`, preserving the source list price. Pricing and availability are checked separately.

Tests use small synthetic fixtures in `tests/fixtures/data/`. Original challenge inputs are intentionally excluded from version control. Order lookup, policy retrieval and LLM integration are not implemented.

## Local setup

Requires Python 3.12 or newer. The development environment uses Python 3.12.13.

From the project root, run these commands in PowerShell with `uv` installed:

```powershell
uv python install 3.12
uv venv --python 3.12 --seed .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
