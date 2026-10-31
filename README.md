# Emporio Support Agent

This project aims to build a small Python customer-service agent for Emporio da Musica, a fictional musical instrument store, using supplied store data and policies for the Artefact AI Engineer challenge.

## Development status

Implementation is in progress. Deterministic CSV loading and structural validation are available through `emporio_support_agent.data.load_store_data(data_dir)`. Exact catalog lookup/filtering, product availability, unit-price quotes, owner-scoped order lookup and policy extraction/retrieval are also implemented. The customer-service agent is not implemented yet.

The loader returns frozen records and tuple collections, preserving source money as `Decimal`, dates and independent product descriptions/specifications. It validates required columns, primary IDs and cross-table references. It accepts `products.csv`-style names or the original `desafio_tecnico_ai_eng - products.csv` naming convention for all six tables, and rejects ambiguous copies. Diagnostic row numbers count CSV records, including the header as row 1.

`emporio_support_agent.catalog` preserves source order and requires active status plus sufficient stock for availability. `emporio_support_agent.pricing` applies one active promotion or the standard 5% PIX discount, never both. Multiple active promotions raise a conflict. Final prices use `Decimal` with cent rounding via `ROUND_HALF_UP`, preserving the source list price. Pricing and availability are checked separately.

`emporio_support_agent.orders` returns only orders belonging to the application-supplied demo customer ID, without customer identity/contact fields. This session identity is not production authentication. Missing and inaccessible orders both return `None`. Order views preserve historical totals, statuses, notes and missing tracking; `estimated_delivery` remains an estimate, not an actual receipt date.

`emporio_support_agent.policies` extracts text PDFs page by page with `pypdf`, detects version and numbered sections, and preserves filename/SHA-256/page provenance. Complete parent sections include their subsections; subsections are also searchable. Lexical ranking counts distinct matched terms, adds twice the title matches, and breaks ties by source order. Case, accents and punctuation are normalized; common PT/EN stop words are ignored. Contradictory source statements remain unchanged. The parser targets left-aligned numbered headings and indented lists, without OCR or semantic search.

Tests use small synthetic fixtures in `tests/fixtures/data/`, in-memory cases and temporary fictional PDFs generated with `pypdf`. Original challenge inputs are intentionally excluded from version control. Return eligibility and LLM integration are not implemented.

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
