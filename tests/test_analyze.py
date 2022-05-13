import pytest
from tests import junjyoukirari_23_ts, salor_moon_C_02_ts, salor_moon_C_02_ptsmap, salor_moon_C_11_ts, invalid_ts, not_existing_ts
import tscutter.analyze
from tscutter.ffmpeg import InputFile
from tscutter.common import PtsMap, InvalidTsFormat
import shutil

def test_Analyze_Success():
    indexPath = tscutter.analyze.AnalyzeVideo(InputFile(junjyoukirari_23_ts))
    assert indexPath.is_file()
    assert indexPath.stat().st_size > 0
    indexPath.unlink()

def test_Analyze_Invalid():
    with pytest.raises(InvalidTsFormat, match='"invalid.ts" is invalid!'):
        tscutter.analyze.AnalyzeVideo(InputFile(invalid_ts))

def test_Split_Success():
    outputFolder = salor_moon_C_02_ts.with_suffix('')
    PtsMap(salor_moon_C_02_ptsmap).SplitVideo(videoPath=salor_moon_C_02_ts, outputFolder=outputFolder)
    assert outputFolder.is_dir()
    shutil.rmtree(outputFolder)

def test_Analyze_BuggyFile():
    indexPath = tscutter.analyze.AnalyzeVideo(InputFile(salor_moon_C_11_ts))
    assert indexPath.is_file()
    assert indexPath.stat().st_size > 0
    indexPath.unlink()
