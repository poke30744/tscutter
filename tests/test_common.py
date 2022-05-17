from tests import salor_moon_C_02_ptsmap
from tscutter.common import PtsMap

def test_PtsMap_Duration():
    ptsMap = PtsMap(salor_moon_C_02_ptsmap)
    assert ptsMap.Duration() == 1800.68

def test_PtsMap_Length():
    ptsMap = PtsMap(salor_moon_C_02_ptsmap)
    assert ptsMap.Length() == 2112393756