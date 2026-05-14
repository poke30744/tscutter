# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Python package for analyzing MPEG2‑TS video files. Detects silence gaps, locates scene‑change frames using histogram chi-squared distance, and builds a `.ptsmap` index. Used by tstriage and tsmarker as a CLI tool.

- Entry point: `tscutter.analyze:main`, console script `tscutter`
- Requires Python ≥3.13

## Commands

```bash
tscutter [--quiet] [--progress] [--version] COMMAND [ARGS]...

# Generate a ptsmap
tscutter index -i video.ts -o index.ptsmap -l 800 -t -80 -s 1

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
- `tscutter.ffmpeg` — `InputFile` class wraps ffmpeg/ffprobe subprocess calls; uses `ffmpeg-python` for probe. Key methods: `GetInfo`, `ExtractStream`, `ExtractFrameDiffs` (histogram-based scene change detection)
- `tscutter.common` — `PtsMap` class for reading `.ptsmap` files; exception classes

## Key Design Decisions

- **Histogram scene-change detection**: `FindSplitPosition` uses 64-bin grayscale histogram chi-squared distance to locate scene changes, replacing the old SAD-based approach. This is codec-agnostic (works on both mpeg2video and h264) and does not depend on I-frame positions.
- **WAV extraction without aresample**: `ExtractStream` converts audio to WAV without the `aresample=async=1` filter, which was found to distort MKV raw AAC timing by ~0.9s compared to TS ADTS AAC.
- **PTS-only**: The refactor removed all POS (byte-position) fields from `PtsMap`. Splitting and extraction use ffmpeg `-ss/-to` instead of byte-range reads.

## Dependencies

- FFmpeg, ffprobe — must be in PATH
- Python: pydub, rich, numpy, Pillow, ffmpeg-python, audioop-lts

## Development

```bash
uv pip install -e .
uv run pytest tests/
```

Tests require sample TS files at `C:\Samples`.
