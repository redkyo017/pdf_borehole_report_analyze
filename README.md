pdf-borehole-report-analyze
===========================

Scripts for quickly inspecting borehole PDF reports and extracting simple chemical table clues.

Prerequisites
-------------
- Python 3.9 or newer (matches `requires-python`)
- [uv](https://github.com/astral-sh/uv) >= 0.4 installed somewhere on your PATH

Environment setup
-----------------
1. (First time only) install uv following the instructions linked above.
2. From the project root run:

```bash
uv sync
```

This command creates a `.venv` directory (if missing) and installs the locked dependencies listed in `pyproject.toml` / `uv.lock`.

Common commands
---------------
- Profile a single PDF:

```bash
uv run python pdf_profiler.py Sample_Report_2.pdf
```

- Scan for chemical tables in a directory:

```bash
uv run python find_chemical_tables.py ./some_folder
```

Managing dependencies with uv
-----------------------------
- Add a new dependency and immediately refresh the lock file:

```bash
uv add <package-name>
```

- Remove a dependency:

```bash
uv remove <package-name>
```

- Re-resolve everything after manual edits to `pyproject.toml`:

```bash
uv lock
```

All commands above automatically keep `pyproject.toml` and `uv.lock` in sync, so future `uv sync` executions recreate the exact same environment.
