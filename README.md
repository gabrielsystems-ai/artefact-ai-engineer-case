# Emporio Support Agent

This project aims to build a small Python customer-service agent for Emporio da Musica, a fictional musical instrument store, using supplied store data and policies for the Artefact AI Engineer challenge.

## Development status

Implementation is in progress. Only the Python package foundation and an import smoke test are available. The customer-service agent is not implemented yet.

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
