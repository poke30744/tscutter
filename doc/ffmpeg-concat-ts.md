# ffmpeg concat for MPEG-TS: PCR/PTS Continuity & Stream Ordering

## Problem

`ExtractClipsPipe` uses byte-range copy (`CopyPartPipe`) to extract program clips and concatenates them at the byte level into a pipe. This has two issues:

1. **`AVPacket.pos` removed in ffmpeg 7+**: see `ffmpeg8-pos-field-fix.md`
2. **Byte-level concat preserves original PTS** — at each clip boundary, PTS jumps (e.g. 120s → 250s). The resulting TS has timestamp discontinuities that downstream consumers (particularly ARIB subtitle extraction with ffmpeg's libaribcaption) may not handle correctly.

## Key Concept: Concat Demuxer vs Concat Protocol

| | concat **demuxer** (`-f concat -i list.txt`) | concat **protocol** (`-i "concat:a|b"`) |
|---|---|---|
| PTS adjustment | **Yes** — adds cumulative duration offset | **No** — byte-level |
| Stream matching | By index order | N/A |
| Input requirement | Seekable files only | Files (byte-level) |
| Pipe support | **No** | **No** |

## Stream Ordering Problem

The concat demuxer matches streams **by index, not by PID**. If two files have the same streams in different index order, concat will mismatch them (e.g. video with epg data).

Example from a real ISDB-T recording:
```
File 1: 0:0=video, 0:1=audio, ..., 0:10=epg
File 2: 0:0=epg,   0:1=video,  ...
```

This happens because the PAT/PMT can list PIDs in different orders in different segments of the same broadcast.

### Solution: PID-based remux before concat

```bash
ffmpeg -i input.ts \
  -map '0:#0x100' -map '0:#0x110' -map '0:#0x130' \
  -map '0:#0x138' -map '0:#0x140' -map '0:#0x150' \
  -map '0:#0x160' -map '0:#0x161' -map '0:#0x15e' \
  -map '0:#0x15f' -map '0:#0x12' \
  -c copy -copy_unknown output.ts
```

`0:#0xPID` maps by TS PID, ensuring consistent stream order regardless of PAT ordering. `-copy_unknown` is needed for streams ffmpeg doesn't recognize (e.g. `Unknown: none` types).

## Concat Demuxer with inpoint/outpoint (FAILED)

The concat demuxer supports `inpoint` and `outpoint` directives to extract segments from the same file:

```
ffconcat version 1.0
file 'source.ts'
inpoint 10.5
outpoint 120.3
```

**Does NOT work for MPEG-TS.** Tested with ffmpeg 8.1: output is empty (0 frames, 0 bytes). Likely because the concat demuxer's seek mechanism can't locate the correct byte position in TS files for non-zero inpoints.

## Verified Working: remux first, then concat

### Step 1: PID-based remux (standardize stream order)

All files end up with identical stream layout:
```
0:0 = Video (0x100)
0:1 = Audio (0x110)
0:2 = ARIB Subtitle (0x130)
0:3-9 = data/unknown
0:10 = EPG (0x12)
```

### Step 2: Concat demuxer

```bash
ffmpeg -f concat -safe 0 -i list.txt -c copy -copy_unknown -map 0 merged.ts
```

No `-fflags +genpts` needed — the concat demuxer automatically adjusts PTS/DTS by cumulative duration.

### Verified results on 40-min ISDB-T recording

- **Video DTS**: perfectly continuous across all 3 concat boundaries, 0.033s steps
- **Audio PTS**: 0 backward jumps across all packets
- **ARIB Subtitle PTS**: full continuity, 0 backward jumps, all packets preserved
- **11 streams**: all preserved when wanted, or selectable via `-map`

## Strip (Stream Filtering) During Remux

The "strip" step in the pipeline filters TS streams. Current `StripTsCmd`:

```python
# StripTsCmd: drops subtitle and data streams
ffmpeg -i inFile -c:v copy (-c:a copy | fixAudio)
       -map 0:v -map 0:a -ignore_unknown
       -metadata:s:a:0 language=jpn -f mpegts outFile
```

If the pipeline moves to ffmpeg concat, the concat step must **retain** subtitles (add `-map 0:s`) because the subtitle extraction (ARIB→ASS) also reads from the concat output.

### Strip file size reduction

| | Original (broadcast) | Stripped |
|---|---|---|
| Size | 4.5 GB | 3.6 GB |
| Streams | 11 (video+audio+subtitle+8 data/unknown/EPG) | 3 (video+audio+subtitle) |
| Reduction source | ~8 data streams removed + broadcast null packets (CBR padding) | |

Video/audio are `-c copy` — elementary stream data is identical. The 0.9 GB difference is entirely container overhead and removed data streams.

## Future Refactoring Directions

### Option A: TS parser for byte positions (keep pipe architecture)

Replace `pos` field dependency with direct TS parsing (188-byte packet scanning) to find I-frame byte positions via PTS matching. Documented in `ffmpeg8-pos-field-fix.md`. Keeps the current pipe-based architecture but adds TS parsing complexity.

### Option B: ffmpeg concat with temp files (clean but has I/O cost)

1. Extract clips: `ffmpeg -ss start -to end -c copy clip_N.ts` for each program segment
2. PID-remux if needed to standardize stream order
3. Concat demuxer: PTS-continuous merged TS
4. Pipe to encode + subtitle extraction

Trade-off: temp file I/O vs. clean timestamp handling and no pos dependency.

### Option C: Single ffmpeg call (no pipe, no Tee)

Use ffmpeg's multi-output to produce MP4 and ASS in one command:
```bash
ffmpeg -f concat -i list.txt \
  -c:v libx264 ... -c:a copy \
  -map 0:v -map 0:a output.mp4 \
  -map 0:s -c:s ass subtitle.ass
```

Simplest code, but loses the piped Tee architecture and requires restructuring EncodeTsCmd.

## Test Environment

- ffmpeg 8.1 (Lavf62.12.100)
- ISDB-T MPEG2-TS with ARIB captions (Profile A)
- libaribcaption decoder
