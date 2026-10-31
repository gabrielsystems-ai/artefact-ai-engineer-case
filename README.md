# Emporio Support Agent

This project aims to build a small Python customer-service agent for Emporio da Musica, a fictional musical instrument store, using supplied store data and policies for the Artefact AI Engineer challenge.

## Development status

Implementation is in progress. Deterministic CSV loading and structural validation are available through `emporio_support_agent.data.load_store_data(data_dir)`. Exact catalog lookup/filtering, product availability, unit-price quotes, owner-scoped order lookup and policy extraction/retrieval are also implemented. A programmatic customer-service agent now integrates these tools through the OpenAI Responses API; the CLI and final conversation example files remain pending.

The loader returns frozen records and tuple collections, preserving source money as `Decimal`, dates and independent product descriptions/specifications. It validates required columns, primary IDs and cross-table references. It accepts `products.csv`-style names or the original `desafio_tecnico_ai_eng - products.csv` naming convention for all six tables, and rejects ambiguous copies. Diagnostic row numbers count CSV records, including the header as row 1.

`emporio_support_agent.catalog` preserves source order and requires active status plus sufficient stock for availability. `emporio_support_agent.pricing` applies one active promotion or the standard 5% PIX discount, never both. Multiple active promotions raise a conflict. Final prices use `Decimal` with cent rounding via `ROUND_HALF_UP`, preserving the source list price. Pricing and availability are checked separately.

`emporio_support_agent.orders` returns only orders belonging to the application-supplied demo customer ID, without customer identity/contact fields. This session identity is not production authentication. Missing and inaccessible orders both return `None`. Order views preserve historical totals, statuses, notes and missing tracking; `estimated_delivery` remains an estimate, not an actual receipt date.

`emporio_support_agent.policies` extracts text PDFs page by page with `pypdf`, detects version and numbered sections, and preserves filename/SHA-256/page provenance. Complete parent sections include their subsections; subsections are also searchable. Lexical ranking counts distinct matched terms, adds twice the title matches, and breaks ties by source order. Case, accents and punctuation are normalized; common PT/EN stop words are ignored. Contradictory source statements remain unchanged. The parser targets left-aligned numbered headings and indented lists, without OCR or semantic search.

Tests use small synthetic fixtures in `tests/fixtures/data/`, in-memory cases and temporary fictional PDFs generated with `pypdf`. Original challenge inputs are intentionally excluded from version control. An automated return-approval engine is not implemented.

`emporio_support_agent.tools` exposes five provider-independent tools through `get_tool_definitions()` and `execute_tool(context, name, arguments)`. Explicit schemas and local validation reject unexpected arguments; order identity comes only from application-owned `ToolContext`. Outputs use JSON-native values, decimal money strings and ISO dates. Product discovery matches all normalized query terms across source fields, prioritizes name/category/description/specs, and preserves source order for ties. Budgets use current unit prices from the pricing module.

`emporio_support_agent.agent.SupportAgent(context=...)` provides `respond(message)`, returning an immutable `AgentReply` with customer-facing text and tool-name/count metadata. The default model is `gpt-6.1-terra`, tested live with `openai==3.42.0` on Python 3.12.13. Product prices/availability, promotion plus PIX, owner-scoped orders, return-policy clarification, English opening hours and conflicting contact sources were checked through real model/tool exchanges. These verification runs are not final challenge examples.

`emporio_support_agent.openai_adapter` converts the five internal schemas to strict function tools: all provider properties are required, internally optional properties permit null (including enum values), and optional null arguments are omitted before internal validation. Deterministic tools remain authoritative. Each request resends the store instructions and approved tools, disables parallel calls, and uses matching `call_id` values for tool outputs. Each customer turn allows at most four tool rounds and eight executions by default, with a 1,024-token response cap. The default client has a 45-second timeout and no automatic retries. Provider failures raise safe project errors, and failed turns retain the last completed session state.

Local conversation state consists only of the last completed response ID in memory, chained with `previous_response_id`. Requests use `store=True`, so conversation content is stored at OpenAI: this is a prototype tradeoff, not local-only content storage. There is no local disk/database history or cross-process recovery. Use one agent instance sequentially per demo customer context. The runtime uses preloaded snapshots, not a live ERP or carrier integration.

Supply the API key through `OPENAI_API_KEY` in the local process environment and never commit it; `.env` files are not loaded automatically. Normal pytest execution is offline and uses a fake Responses client with real deterministic tools. Real provider checks run separately.

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
