import json, tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from tscutter.analyze import MergeIntervals, GeneratePtsMap


def test_MergeIntervals_empty():
    assert MergeIntervals([]) == []


def test_MergeIntervals_single():
    assert MergeIntervals([[100, 200]]) == [[100, 200]]


def test_MergeIntervals_overlapping():
    result = MergeIntervals([[100, 200], [150, 250], [300, 400]])
    assert result == [[100, 250], [300, 400]]


def test_MergeIntervals_non_overlapping():
    result = MergeIntervals([[100, 200], [300, 400]])
    assert result == [[100, 200], [300, 400]]


def test_GeneratePtsMap_no_pos_fields():
    """Verify GeneratePtsMap produces no _pos fields."""
    cutLocations = [
        (
            {'ptsTime': 99.0, 'sad': 0.1},
            {'ptsTime': 99.0, 'sad': 0.9},
            {'ptsTime': 99.5, 'sad': 0.2},
        ),
    ]
    mockInputFile = MagicMock()
    mockInputFile.GetInfo.return_value.duration = 200.0

    ptsmap = GeneratePtsMap(mockInputFile, cutLocations)

    # Check no _pos fields exist anywhere
    for key, entry in ptsmap.items():
        assert 'prev_end_pos' not in entry, f'_pos field found at key {key}'
        assert 'next_start_pos' not in entry, f'_pos field found at key {key}'
        assert 'prev_end_pts' in entry
        assert 'next_start_pts' in entry

    # Check the cut point entry
    assert 99.0 in ptsmap
    assert ptsmap[99.0]['prev_end_pts'] == 99.0
    assert ptsmap[99.0]['next_start_pts'] == 99.5


def test_SplitVideo_uses_ffmpeg_with_pts():
    """Verify SplitVideo calls ffmpeg with -ss/-to (time-based), not byte positions."""
    from tscutter.common import PtsMap
    import tempfile

    ptsmap = {
        "0.0": {"prev_end_pts": 0.0, "next_start_pts": 0.0, "prev_end_sad": 0.0, "next_start_sad": 0.0},
        "100.0": {"prev_end_pts": 100.0, "next_start_pts": 100.5, "prev_end_sad": 0.1, "next_start_sad": 0.2},
        "200.0": {"prev_end_pts": 200.0, "next_start_pts": 200.0, "prev_end_sad": 0.0, "next_start_sad": 0.0},
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ptsmap', delete=False) as f:
        json.dump(ptsmap, f)
        ptsmap_path = Path(f.name)

    try:
        with patch('tscutter.common.subprocess.run') as mock_run:
            pm = PtsMap(ptsmap_path)
            with tempfile.TemporaryDirectory() as tmpdir:
                out = Path(tmpdir) / 'output'
                pm.SplitVideo(Path('/fake/video.ts'), out)

                assert mock_run.call_count == 2  # 2 clips
                call_args = mock_run.call_args_list[0][0][0]
                ss_idx = call_args.index('-ss')
                to_idx = call_args.index('-to')
                i_idx = call_args.index('-i')
                assert ss_idx > i_idx, '-ss must be after -i'
                assert to_idx > i_idx, '-to must be after -i'
                assert call_args[ss_idx + 1] == '0.0'
                assert call_args[to_idx + 1] == '100.0'
                assert '-c' in call_args
                assert 'copy' in call_args
    finally:
        ptsmap_path.unlink()
