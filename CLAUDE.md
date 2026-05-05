# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Python package for analyzing MPEG2‑TS video files. Detects silence gaps, locates scene‑change frames using sum‑of‑absolute‑differences, and builds a `.ptsmap` index. Used by tstriage and tsmarker as a CLI tool.

- Entry point: `tscutter.analyze:main`, console script `tscutter`
- Requires Python ≥3.13

## Commands

```bash
tscutter [--quiet] [--progress] COMMAND [ARGS]...

# Generate a ptsmap
tscutter analyze -i video.ts -o index.ptsmap -l 800 -t -80 -s 1

# Probe video info (JSON to stdout)
tscutter probe -i video.ts

# List all clips from a ptsmap
tscutter list-clips -x index.ptsmap

# Select candidate long clips
tscutter select-clips -x index.ptsmap --min-length 150
```

## Architecture

- `tscutter.analyze` — CLI entry point and main orchestration: silence detection, scene‑change location, PTS map generation
- `tscutter.audio` — silence detection using pydub/ffmpeg
- `tscutter.ffmpeg` — `InputFile` class wraps ffmpeg/ffprobe subprocess calls; uses `ffmpeg-python` for probe
- `tscutter.common` — `PtsMap` class for reading `.ptsmap` files; `SplitVideo` (used by tsmarker's `MarkerMap.Cut`); `CopyPart`/`CopyPartPipe` utilities; exception classes

## Dependencies

- FFmpeg, ffprobe, ffmpeg5 — must be in PATH
- Python: pydub, rich, numpy, Pillow, ffmpeg-python, audioop-lts

## Development

```bash
uv pip install -e .
uv run pytest tests/
```

Tests require sample TS files at `C:\Samples`.
