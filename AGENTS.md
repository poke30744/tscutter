# tscutter Agent Instructions

High-signal, repo-specific guidance for OpenCode agents working in this repository.

## Overview
- Python package for cutting MPEG2‑TS video files into clips based on silence detection and scene change analysis.
- Primary entry point: `tscutter` console script (calls `tscutter.analyze:main`).
- Requires Python >=3.8 (see `pyproject.toml`).
- Uses `uv` for dependency management and packaging.

## Commands
- **Main CLI** (via `tscutter` console script):
  ```bash
  tscutter analyze --input video.ts --output index.ptsmap
  tscutter split --input video.ts --index index.ptsmap --output folder
  ```
- **Module entry points** (run with `python -m`):
  ```bash
  python -m tscutter.analyze -h
  python -m tscutter.audio -h
  ```
- **Building distribution** (Jenkins flow):
  ```bash
  uv build
  ```
- **Development installation**:
  ```bash
  uv pip install -e .
  ```

## Testing
- Uses `pytest` (configured in `.vscode/settings.json`).
- Tests rely on sample files located at `C:\Samples` (see `tests/__init__.py`). If samples are unavailable, adjust the `samplesDir` path or skip tests.
- Run all tests: `pytest tests/`.
- Single test: `pytest tests/test_common.py::test_PtsMap_Properties`.

## Dependencies & External Tools
- **FFmpeg** – required for audio analysis and frame property extraction (called via subprocess).
- **pywin32** – optional Windows‑only dependency for COM interop (added automatically on Windows).
- No other external tools required.

## Ignored Artifacts
- Generated `.ptsmap` files, split video clips, and temporary files are not tracked.

## Conventions
- No specific linting or formatting config; follow existing code style.
- Commit messages are straightforward (no special template).
- Jenkins builds with uv Python 3.9 in a Docker container (see `Jenkinsfile`).