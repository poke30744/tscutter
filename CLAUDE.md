# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Python package for cutting MPEG2‑TS video files into clips based on silence detection and scene‑change analysis. The tool identifies silent intervals, locates nearby scene‑change frames (using sum‑of‑absolute‑differences), and builds a PTS map that can be used to split the original TS file byte‑accurately.

- Entry point: `tscutter` console script (calls `tscutter.analyze:main`).
- Requires Python ≥3.8 (see `pyproject.toml`).
- Uses `uv` for dependency management and packaging.
- Package version is dynamic: `0.1.{BUILD_NUMBER}` where `BUILD_NUMBER` is taken from the environment variable (see Jenkinsfile).

## Commands

### Main CLI
```bash
# Generate a PTS map (.ptsmap) from a TS file
tscutter analyze --input video.ts --output index.ptsmap

# Split a TS file using an existing PTS map
tscutter split --input video.ts --index index.ptsmap --output folder
```

### Module entry points
```bash
python -m tscutter.analyze -h
python -m tscutter.audio -h
```

### Development & Packaging
```bash
# Install in development mode
uv pip install -e .

# Build distribution
uv build

# Run all tests (requires sample files at C:\Samples)
pytest tests/
```

## Architecture

### Core Modules
- `tscutter.analyze` – main orchestration: silence detection, scene‑change location, PTS map generation.
- `tscutter.audio` – silence detection using `pydub`/`ffmpeg`.
- `tscutter.ffmpeg` – `InputFile` class wraps `ffmpeg`/`ffprobe` subprocess calls for extracting streams, frame properties, and video metadata. Uses `ffmpeg-python` for `ffprobe` JSON probing.
- `tscutter.common` – `PtsMap` class for reading/writing `.ptsmap` files and splitting video by byte positions; `FormatTimestamp` and `ClipToFilename` utilities. Commands are resolved via `shutil.which()`.

### Workflow
1. `DetectSilence` (audio module) extracts a WAV track, runs `pydub.silence.detect_silence`.
2. Merged silence intervals are passed to `LookingForCutLocations`, which extracts frame‑property lists (`ExtractFrameProps`) and selects the highest‑SAD frame within each interval as a candidate cut point.
3. `GeneratePtsMap` builds a dictionary mapping PTS times to frame metadata (position, SAD, surrounding I‑frame positions).
4. The `.ptsmap` file is saved as JSON.
5. `PtsMap.SplitVideo` reads the map and copies byte ranges from the original TS file to produce clip files.

### Dependencies & External Tools
- **FFmpeg** – required for audio extraction and frame‑property analysis. Must be in `PATH`.
- Python dependencies: `pydub`, `tqdm`, `numpy`, `Pillow`, `ffmpeg-python`.

## Testing

- Uses `pytest` (configured in `.vscode/settings.json`).
- Tests rely on sample TS files located at `C:\Samples` (see `tests/__init__.py`). If samples are unavailable, adjust the `samplesDir` path or skip tests.
- Run a single test: `pytest tests/test_common.py::test_PtsMap_Properties`.

## CI/CD

- Jenkins pipeline defined in `Jenkinsfile` builds with uv Python 3.9 in a Docker container.
- Builds distribution wheel, runs smoke tests, optionally publishes to Test PyPI.
- Version derived from environment variable `BUILD_NUMBER`.

## Ignored Artifacts

- Generated `.ptsmap` files, split video clips, and temporary files (e.g., `_metadata/`, `logoNet_frames_*`, `logoNet_wav_*`) are not tracked.

## Conventions

- No specific linting or formatting config; follow existing code style.
- Commit messages are straightforward (no special template).