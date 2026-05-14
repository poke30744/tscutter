# tscutter

Analyze and split MPEG2-TS video files. Detects silence gaps, finds scene change points, and generates `.ptsmap` index files.

## CLI Commands

```
tscutter [--quiet] [--progress] [--version] COMMAND [ARGS]...
```

| Command | Description | Input | Output |
|---|---|---|---|
| `index` | Silence → scene change → .ptsmap | TS file | `.ptsmap` |
| `probe` | ffprobe video info | TS file | stdout JSON |
| `list-clips` | List all clips from ptsmap | `.ptsmap` | stdout JSON |
| `select-clips` | Long candidate clips | `.ptsmap` | stdout JSON |

### Examples

```
tscutter --quiet index -i input.ts -o output.ptsmap -l 800 -t -80 -s 1
tscutter probe -i input.ts
tscutter list-clips -x index.ptsmap
tscutter select-clips -x index.ptsmap --min-length 150
```

## Dependencies

- Python ≥3.13
- ffmpeg, ffprobe
- pydub, numpy, Pillow, ffmpeg-python, tqdm, audioop-lts
