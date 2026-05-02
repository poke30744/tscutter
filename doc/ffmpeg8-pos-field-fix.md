# ffmpeg 8.1 `pos:` Field Fix

## Goal

Replace the `pos:` field removed from ffmpeg 8.1's `showinfo` filter with an equivalent data source. The `pos` value (`AVPacket.pos` — byte position in the TS file) is critical for clip extraction via `CopyPartPipe`.

**Requirement**: byte positions must be **exactly identical** to what old ffmpeg's showinfo produced. Estimation is unacceptable.

## Why `pos` Matters

- `tscutter/ffmpeg.py::ExtractFrameProps` uses showinfo to get per-frame metadata
- `pos` = byte position of the frame's first TS packet → used by `ExtractClipsPipe` for byte-range copying
- Downstream chain: `FindSplitPosition` → `GeneratePtsMap` → `.ptsmap` → `ExtractClipsPipe`

## Approaches Tried

### 1. ❌ Estimation from bitrate (`pos ≈ ptsTime × fileSize/duration`)

Result: SAD values and cut point times matched reference, but byte positions differed by 600-850KB per cut point. **Unacceptable.**

### 2. ❌ `ffprobe -show_frames -read_intervals` with percentage syntax

`-read_intervals "100%+3"` always returns frames from time 0 regardless of start percentage. **ffprobe 8.1 bug.**

### 3. ❌ `ffprobe -show_frames -read_intervals` with `HH:MM:SS` syntax

`-read_intervals "05:03:57"` correctly seeks, but returns empty output for `-show_frames`. Only works with `-show_packets`.

### 4. ❌ `ffprobe -show_packets -read_intervals "HH:MM:SS"` + PTS matching

Packets correctly seeked and returned. But:
- `-show_packets` includes non-frame packets (PES headers, PCR) that pollute the PTS→pos mapping
- HH:MM:SS seek skips the first 0.5s of frames (seek imprecision)
- Result: matched frames to wrong packets, pos values off by 600-850KB

### 5. ❌ `ffprobe -show_frames -read_intervals "0%+N"` + PTS matching

Reads all frames from time 0 (bug: percentage always starts from 0). Matching by pts_time failed because showinfo's output-relative PTS and ffprobe's absolute PTS differ by ~0.067s (2 frames) due to different decoding paths.

### 6. ❌ `-f framecrc` / `-f framemd5` / `-debug packets` / `-vstats`

None of these ffmpeg output formats include per-frame `pkt_pos`.

### 7. ✅ **Selected: Direct TS file parsing**

Parse the raw TS file (188-byte packets) to find exact byte positions by PTS matching. This reads `AVPacket.pos` from the same source as old showinfo.

## Confirmed Facts

- `ffprobe -show_packets -read_intervals "HH:MM:SS"` works (correct seek, exact `pos` values)
- ffprobe `pkt_pos` at a given PTS matches old showinfo `pos` at the same frame
- SAD values from showinfo are still correct in ffmpeg 8.1 (only `pos:` removed)
- `mean`/`stdev`/`checksum`/`planeChecksum` fields are **never used downstream**

## Implementation Attempts & Failures

### Attempt A: Direct TS parsing + PTS matching

**Approach**: Parse TS file for all video PES headers → get list of (abs_pts, byte_pos). Match showinfo frames by nearest PTS.

**Result**: ❌ PTS matching picks wrong frames.

**Root cause**: Decoder (showinfo) PTS and PES (TS file) PTS differ by a **constant ~0.067s offset** (~2 frames at 30fps). Since nearest-PTS matching picks the frame with the closest PTS value, the constant offset biases the match toward the wrong frame. A showinfo frame at PTS=T should match a TS frame at PES_pts=T-0.067s, but the nearest match to T finds a different TS frame whose PES_pts is closer to T than T-0.067s is.

**Verified**: The 0.067s offset is perfectly constant across the entire 1205s file (±0.000004s). All 10 reference pos values exist at the expected byte positions in the TS file — the issue is solely matching.

### Attempt B: Frame index matching with byte position estimation

**Approach**: For ss>0 (seek into file), estimate the seek point's byte position as `ss/duration * file_size`, find nearest TS frame.

**Result**: ❌ Variable bitrate makes estimate inaccurate (off by 300-500KB for later cut points).

### Attempt C: Frame index matching with frame rate estimation

**Approach**: Estimate seek point as `start_off_0 + int(ss * fps)`. Use PTS interval matching (±5 frames) for refinement.

**Result**: ❌ Frame rate estimation drifts (off by 4-7 frames due to non-uniform frame distribution). PTS interval matching can't refine because **PTS intervals are nearly uniform** (0.033s at 30fps) — all candidate alignments have the same interval score.

### Attempt D: PTS offset variance minimization

**Approach**: Binary search for approximate match, then within ±N frames find the alignment with minimum PTS offset variance (correct alignment has constant offset).

**Result**: ❌ ALL candidate alignments have zero variance. The offset for alignment A is a constant C, and for A+1 is C + frame_interval (also a constant). Standard deviation is zero for all candidates. **Cannot distinguish correct alignment.**

### Attempt E: Cached PTS offset from ss=0 call

**Approach**: The first `ExtractFrameProps` call has ss=0 (first silence interval starts near 0). Cache the PTS offset from this call and apply it to subsequent ss>0 calls.

**Result**: ❌ The PTS offset between showinfo and PES **varies per call** (depends on the seek point). At ss=0: offset≈0.083s. At ss=2.57: offset≈0.192s. At ss=205: different again. Caching from ss=0 gives wrong correction.

**Root cause**: The decoder's starting PTS depends on where the seek lands in the GOP. The `showinfo_pts - PES_pts` offset is constant WITHIN a single call, but DIFFERS between calls with different ss values.

### Attempt F: Frame type (I/P/B) pattern matching

**Approach**: Extend TS parser to extract MPEG2 picture_coding_type from PES payload. Match showinfo frame type sequence to TS frame type sequence.

**Result**: ❌ Only ~1/3 of TS frames yield valid types (I and P frames; B-frame picture start codes are often deeper in the PES payload or spread across TS packet boundaries). The sparse type data makes pattern matching unreliable — GOP patterns repeat every 12-15 frames, causing false matches.

### Attempt G: I-frame matching

**Approach**: Match the first I-frame in showinfo to the nearest I-frame in TS. I-frames are ~15 frames apart, so within a ±15 frame search range, find and match I-frames only.

**Result**: ❌ PTS offset causes the nearest PTS-based I-frame to be the wrong one (off by 1 GOP = 15 frames). Dual I-frame verification also fails because the TS type extraction misses B-frame types, making GOP boundary detection unreliable.

### Attempt H: ffprobe -show_packets at seek point

**Approach**: For ss>0, run `ffprobe -show_packets -read_intervals "HH:MM:SS%+#1"` at the estimated absolute time to get the exact `pos` of the first packet. Look up this pos in the TS frame list.

**Result**: Interrupted before verification. The `-read_intervals` HH:MM:SS syntax works correctly for `-show_packets` in ffprobe 8.1, so this approach should give exact pos values. However, the HH:MM:SS conversion uses `ts_frames[0][0] + propList[0]['ptsTime']` which includes the PTS offset error (0.067s). This might cause the ffprobe query to return a packet 1-2 frames away from the correct one.

## Key Technical Findings

### PTS offset between decoder (showinfo) and PES (TS file)

- **Constant 0.067423s ± 0.000004s** across the entire 1205s file for matching frames
- Caused by decoder initialization: the decoder's first output frame has abs_pts = 18233.028844, but showinfo reports it as pts_time=0.434 (due to output stream timebase adjustment)
- The PES PTS of this frame is `ts_frames[8][0] - ts_frames[0][0] = 0.367s` (file-relative)
- showinfo_pts − PES_pts = 0.434 − 0.367 = 0.067s
- This offset is constant for ALL frames within a single `ExtractFrameProps` call
- But it VARIES between calls with different `-ss` values (decoder starts at different points)

### Frame ordering

- Showinfo with `-vsync 0` outputs frames in **file/decode order** (not display order)
- TS parser also produces frames in file order
- So frame-index matching is correct IF the start offset is known
- The new ffmpeg/ffprobe 8.1 decoder drops the first ~8 file-order frames at ss=0 (open GOP B-frames missing reference)

### Frame type extraction from TS

- Only I and P frames (~1/3 of total) have the picture start code (0x00000100) near the beginning of their PES payload
- B-frame picture start codes are often too deep in the PES payload or span multiple TS packets
- This makes frame-type-based matching unreliable

## Why `pos` Matching Is Hard for ss>0

The core difficulty: `ExtractFrameProps` is called with various `ss` values (not always 0). The `FindSplitPosition` function calls it with `ss = max(interval_start - 1, 0)`. For the first silence interval starting near 0, ss=0 works. For later intervals, ss>0.

With ss>0, ffmpeg seeks in the input file. The decoder starts at a different point, dropping a different number of initial frames. The first showinfo frame's position in the TS frame list is unknown.

**The only known-good method** is matching at ss=0 (via `_GetFirstPts()` + TS PTS matching). All attempts to extend this to ss>0 have failed because there is no reliable, PTS-independent way to determine which TS frame corresponds to the first showinfo frame after a seek.

## Potential Alternative Approaches

### Option 1: Always use ss=0 for the entire file

Modify `LookingForCutLocations` to call `ExtractFrameProps(0, duration)` once, then filter frames by ptsTime for each silence interval. This eliminates the ss>0 matching problem entirely.

- **Pro**: Guaranteed correct pos values (ss=0 matching is proven exact)
- **Con**: Much slower — each interval's ffmpeg run decodes from the beginning (5× overhead). BMP extraction for the entire file would consume significant temp space (~36000 BMP files).

### Option 2: ffprobe -show_packets at seek point (Attempt H, untested)

Use ffprobe's `-show_packets -read_intervals "HH:MM:SS"` feature to get the exact `pos` of the first packet at the seek point. This gives the same `pos` value that the old showinfo's `AVPacket.pos` would have had.

- **Pro**: Uses the same data source as old showinfo (ffprobe reads from the demuxer)
- **Con**: Requires correct absolute time conversion; HH:MM:SS precision may affect accuracy

### Option 3: Refactor analyze to single ExtractFrameProps call

Run `ExtractFrameProps(0, duration, nosad=True)` once to get all frame positions (no BMPs). Then for each silence interval, run a lightweight ffmpeg call for SAD-only BMP extraction in the specific range, using the pre-computed pos values.

- **Pro**: Combines correctness of ss=0 with efficiency of range-limited BMP extraction
- **Con**: Requires moderate refactoring of the analyze pipeline

## Test Data

- Anime test file: `C:\Users\xiaoju\Desktop\TestData\recorded\...おしりたんてい...m2ts`
- Reference ptsmap: `C:\Users\xiaoju\Desktop\TestData/...おしりたんてい...ptsmap`  
- Comparison script: verify 7 entries (5 cut points), pos values must be exact match
