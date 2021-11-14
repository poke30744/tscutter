import pytest
from tests import junjyoukirari_23_ts, salor_moon_C_02_ts, salor_moon_C_02_ptsmap, salor_moon_C_11_ts, invalid_ts, not_existing_ts
import tscutter.analyze
from tscutter.common import InvalidTsFormat
import shutil

def test_Analyze_Success():
    indexPath = tscutter.analyze.AnalyzeVideo(junjyoukirari_23_ts)
    assert indexPath.is_file()
    assert indexPath.stat().st_size > 0
    indexPath.unlink()

def test_Analyze_Invalid():
    with pytest.raises(InvalidTsFormat, match='"invalid.ts" is invalid!'):
        tscutter.analyze.AnalyzeVideo(invalid_ts)

def test_Split_Success():
    outputFolder = tscutter.analyze.SplitVideo(salor_moon_C_02_ts, salor_moon_C_02_ptsmap)
    assert outputFolder.is_dir()
    shutil.rmtree(outputFolder)

def test_Analyze_BuggyFile():
    indexPath = tscutter.analyze.AnalyzeVideo(salor_moon_C_11_ts)
    assert indexPath.is_file()
    assert indexPath.stat().st_size > 0
    indexPath.unlink()
