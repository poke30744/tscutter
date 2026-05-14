import json, tempfile
from pathlib import Path
from tscutter.common import PtsMap, ClipToFilename, FormatTimestamp


def test_PtsMap_Duration():
    ptsmap = {
        "0.0": {"prev_end_pts": 0.0, "next_start_pts": 0.0},
        "100.0": {"prev_end_pts": 100.0, "next_start_pts": 100.5},
        "200.0": {"prev_end_pts": 200.0, "next_start_pts": 200.0},
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ptsmap', delete=False) as f:
        json.dump(ptsmap, f)
        path = Path(f.name)
    try:
        pm = PtsMap(path)
        assert pm.Duration() == 200.0
        assert len(pm.Clips()) == 2
        clips = pm.Clips()
        assert clips[0] == (0.0, 100.0)
        assert clips[1] == (100.0, 200.0)
    finally:
        path.unlink()


def test_SelectClips():
    ptsmap = {
        "0.0": {"prev_end_pts": 0.0, "next_start_pts": 0.0},
        "100.0": {"prev_end_pts": 100.0, "next_start_pts": 100.5},
        "300.0": {"prev_end_pts": 300.0, "next_start_pts": 300.5},
        "500.0": {"prev_end_pts": 500.0, "next_start_pts": 500.0},
    }
    with tempfile.NamedTemporaryFile(mode='w', suffix='.ptsmap', delete=False) as f:
        json.dump(ptsmap, f)
        path = Path(f.name)
    try:
        pm = PtsMap(path)
        selected, total = pm.SelectClips(lengthLimit=50)
        assert len(selected) > 0
        assert total > 0
    finally:
        path.unlink()


def test_ClipToFilename():
    name = ClipToFilename((123.456, 789.012))
    assert name == '0123.456-0789.012.ts'


def test_FormatTimestamp():
    ts = FormatTimestamp(3661.5)
    assert '01:01:01.50' in ts
