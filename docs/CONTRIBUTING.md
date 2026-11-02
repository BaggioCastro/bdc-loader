# Contributing to BDC Loader

Thank you for considering contributing to the BDC Loader plugin. This document explains how to set up a development environment, run tests, and submit changes.

## Development Setup

### Prerequisites

- Python 3.9+
- Git

### Clone and Test

```bash
git clone https://github.com/BaggioCastro/bdc-loader.git
cd bdc-loader
pip install pytest ruff
pytest
```

No QGIS installation is needed to run the tests: the QGIS, Qt, GDAL and matplotlib modules are mocked.

Plugin code must run on QGIS 3 (PyQt5) and QGIS 4 (PyQt6). Import Qt through `qgis.PyQt`, write enums with
their scope (`Qt.AlignmentFlag.AlignLeft`, not `Qt.AlignLeft`), call `exec()` instead of `exec_()`, and read
mouse positions with `event.pos()` or `qt_compat.event_global_pos(event)`.

### Project Layout

| Directory | Purpose |
|-----------|---------|
| `bdc_loader_plugin/core/` | The features of the dialogs (search, download, layer loading, time series) as classes the main dialog and the time series panel inherit, which use Qt; and modules without Qt, such as `download_engine.py`, `vrt_builder.py` and `catalog_data.py` |
| `bdc_loader_plugin/ui/` | User interface dialogs and mixins |
| `bdc_loader_plugin/stac/` | STAC connection layer |
| `bdc_loader_plugin/extraction/` | Data extraction backends (STAC+VRT, WTSS) |
| `bdc_loader_plugin/chart/` | Matplotlib chart system |
| `bdc_loader_plugin/widgets/` | Reusable UI components |
| `bdc_loader_plugin/lib/` | Vendored libraries (`pystac`, `pystac_client`) |
| `bdc_loader_plugin/tests/` | Unit tests |

## Running Tests

```bash
# Full suite (integration tests, which need the BDC servers, are left out)
pytest

# Single file
pytest bdc_loader_plugin/tests/test_download_engine.py

# With coverage
pytest bdc_loader_plugin/tests/ --cov=bdc_loader_plugin --cov-report=term-missing
```

## Linting

```bash
ruff check .
ruff format --check .
```

## Code Style

- All comments, docstrings, and variable names in **English**
- Each `.py` file starts with a module-level docstring
- Remove unused imports, dead code, and unused variables
- Use `from ..logger import warning as _log_warning` for logging in `core/` and `extraction/` modules
- Use `logging.getLogger('bdc_loader')` in modules that already use the stdlib logger

## Messages

Process messages are the texts of the status line (`_set_status`, `_flash_status`), the progress bar
(`setFormat`) and the QGIS message bar (`pushMessage`, `pushWarning`, `pushInfo`). They are written in English
in the code; `i18n_pt.py` gives the Brazilian Portuguese text, in `TEXTS` for a fixed text and in `PATTERNS`
(a regular expression that must match the whole text) for a text built at run time. A new or changed message
needs its Portuguese entry; `tests/test_i18n_coverage.py` lists the ones without it.

Structure by kind:

| Kind | Form | Example |
|------|------|---------|
| In progress | `<Verb-ing> <object>...`, or `<Verb-ing> <object>: <done>/<total> (<n> s)`, no final period | `Searching images (STAC)...`, `Extracting time series (WTSS): 3/10` |
| Done | count first and a past participle, time in parentheses when known, final period | `24 images found.`, `24 layers added to the map (11.6 s, ~0.5 s per layer).` |
| Cancelled | `Cancelling <process>...` while it stops, then `<Process> cancelled.` with any detail | `Loading cancelled: 5 of 24 layers ready (3.1 s).` |
| Failed | `<Process> failed: <reason>.`, built with `i18n.failure_text` | `Search failed: timed out.` |
| Warning or hint | one or two plain sentences, instructions in the imperative | `Click a tile on the map, or press Esc to cancel.` |

Typography:

- No emoji or symbol prefix (the status line shows a level icon), no "Error:" prefix.
- Times as `<n> s`: running counters as integers, final totals with one decimal.
- Sizes with `_format_size`, as `12.3 MB of 40.1 MB (5.2 MB/s)`.
- ASCII `...`; no em dash or ` - ` as a separator, use a colon, a comma or two sentences.
- No `(s)` plurals: `i18n.count_label(n, "image", "images")` writes `1 image` or `24 images`, and the
  Portuguese pattern gives both forms. Call it inside the f-string passed to `_set_status`, so the coverage
  test sees the text.
- Sentence case. No "successfully", no exclamation marks, no "please".

Vocabulary:

| English | Portuguese | Meaning |
|---------|------------|---------|
| image | imagem | one date of a collection: a search result, a STAC item |
| scene | cena | a source scene grouped into a mosaic date |
| date | data | a mosaic date |
| layer | camada | a QGIS layer (never "VRT" in a message) |
| crop | recorte | an image cut to the area |
| tile, grid | tile, grade | |
| band | banda | |
| point, time series, history | ponto, série temporal, histórico | |
| file, folder | arquivo, pasta | |
| the BDC | o BDC | the server; STAC, WTSS and WFS appear only as the source, in parentheses |
| search, download, downloading | busca, download, baixando | |
| overview, contrast | overview, contraste | |

Process names in cancel, failure and done messages: Search (Busca), Loading layers (Carregamento das
camadas), Download, Grid download (Download da grade), Time series extraction (Extração da série temporal),
Opening the image of `<date>` (Abrindo a imagem de `<data>`).

## Submitting Changes

1. Fork the repository and create a branch from `main`
2. Make your changes with clear, descriptive commits
3. Ensure all tests pass: `pytest`
4. Ensure no lint errors: `ruff check .` and `ruff format --check .`
5. Open a Pull Request against `main`

## Reporting Issues

Use [GitHub Issues](https://github.com/BaggioCastro/bdc-loader/issues) with one of the templates below.

### Bug Report

Include:
- QGIS version and OS
- Steps to reproduce
- Expected vs actual behavior
- QGIS Log Messages output (View > Log Messages > BDC Loader)

### Feature Request

Include:
- Description of the desired behavior
- Use case / motivation
- Any relevant BDC documentation links

## License

By contributing, you agree that your contributions will be licensed under the GPL v3 license.
