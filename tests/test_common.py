import json, tempfile
from pathlib import Path
from tscutter.common import PtsMap, FormatTimestamp


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


def test_FormatTimestamp():
    ts = FormatTimestamp(3661.5)
    assert '01:01:01.50' in ts
