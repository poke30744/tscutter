import json, tempfile
from pathlib import Path
from unittest.mock import MagicMock
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


