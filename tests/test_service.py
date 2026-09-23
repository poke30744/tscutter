import json, tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tscutter.ffmpeg import InputFile, ParseFrameRate
from tscutter.service import ResolveServicePids, ServiceNotFound, ServicePids

FFPROBE_JSON = {
    "programs": [
        {"program_id": 181, "nb_streams": 0, "streams": []},
        {
            "program_id": 182, "nb_streams": 4, "pcr_pid": 256,
            "streams": [
                {"index": 1, "id": "0x131", "codec_type": "video"},
                {"index": 2, "id": "0x132", "codec_type": "audio"},
                {"index": 3, "id": "0x134", "codec_type": "subtitle"},
                {"index": 4, "id": "0x135", "codec_type": "data"},
            ],
        },
    ]
}


def Resolve(serviceId, payload=FFPROBE_JSON):
    with tempfile.NamedTemporaryFile(suffix='.m2ts', delete=False) as f:
        f.write(b'\x47' + b'\x00' * 187)
        path = Path(f.name)
    try:
        completed = MagicMock(stdout=json.dumps(payload).encode())
        with patch('tscutter.service.subprocess.run', return_value=completed):
            return ResolveServicePids(path, serviceId, ffprobe='/usr/bin/ffprobe')
    finally:
        path.unlink()


def test_ResolveServicePids():
    pids = Resolve(182)
    assert pids.programId == 182
    assert pids.pcrPid == 256
    assert pids.video == 0x131
    assert pids.audio == 0x132
    assert pids.subtitle == 0x134
    assert pids.allPids == (0x131, 0x132, 0x134, 0x135)


def test_ResolveServicePids_missing_service():
    with pytest.raises(ServiceNotFound):
        Resolve(999)


def test_ResolveServicePids_ignores_program_without_streams():
    with pytest.raises(ServiceNotFound):
        Resolve(181)


def test_MapSpec():
    pids = ServicePids(182, 0x100, 0x131, 0x132, None, (0x131, 0x132))
    assert pids.MapSpec('v') == '0:#0x131'
    assert pids.MapSpec('a') == '0:#0x132'
    assert pids.MapSpec('s') is None
    assert pids.MapSpec('d') is None


PIDS = ServicePids(182, 0x100, 0x131, 0x132, 0x134, (0x131, 0x132, 0x134))


def MakeInputFile(serviceId=None):
    with tempfile.NamedTemporaryFile(suffix='.m2ts', delete=False) as f:
        f.write(b'\x47' + b'\x00' * 187)
        path = Path(f.name)
    return path, InputFile(path, serviceId=serviceId)


def test_MapSpec_by_index_when_unpinned():
    """Without a service pinned every specifier stays exactly what it was."""
    path, f = MakeInputFile()
    try:
        assert f.MapSpec('v', 0) == '0:v:0'
        assert f.MapSpec('a', 0) == '0:a:0'
        assert f.MapSpec('a', 1) == '0:a:1'
        assert f.MapSpec('s', 0) == '0:s:0'
    finally:
        path.unlink()


def test_ServiceMapArgs_empty_when_unpinned():
    """Unpinned callers must keep passing no -map at all."""
    path, f = MakeInputFile()
    try:
        assert f.ServiceMapArgs('v', 0) == []
    finally:
        path.unlink()


def test_MapSpec_by_pid_when_pinned():
    path, f = MakeInputFile(serviceId=182)
    try:
        with patch('tscutter.ffmpeg.ResolveServicePids', return_value=PIDS):
            assert f.MapSpec('v', 0) == '0:#0x131'
            assert f.MapSpec('a', 0) == '0:#0x132'
            assert f.MapSpec('s', 0) == '0:#0x134'
            assert f.ServiceMapArgs('v', 0) == ['-map', '0:#0x131']
    finally:
        path.unlink()


def MakeAudioOffsetRunner(streamStart, containerStart, firstFrame):
    """Fake the two ffprobe calls and the ffmpeg head probe."""
    def fakeRun(args, **kwargs):
        if 'stream=start_time' in args:
            return MagicMock(stdout=f'{streamStart}\n', stderr='')
        if 'format=start_time' in args:
            return MagicMock(stdout=f'{containerStart}\n', stderr='')
        return MagicMock(stdout='',
                         stderr=f'[Parsed_ashowinfo_1 @ 0x0] n:0 pts:0 pts_time:{firstFrame} z\n')
    return fakeRun


def test_AudioStartOffset():
    """The WAV starts where the resampler puts its first frame."""
    path, f = MakeInputFile()
    try:
        runner = MakeAudioOffsetRunner(27055.957644, 27052.586978, 0.0)
        with patch('tscutter.ffmpeg.subprocess.run', side_effect=runner):
            assert round(f.AudioStartOffset(0), 4) == 3.3707
    finally:
        path.unlink()


def test_AudioStartOffset_keeps_a_lead_in_the_resampler_left_alone():
    """The demuxer cannot parse the track at the head, so ffprobe reports the
    container's start for it — but aresample leaves the lead-in in place, and the
    WAV still begins at the track's first sample."""
    path, f = MakeInputFile()
    try:
        runner = MakeAudioOffsetRunner(27052.586978, 27052.586978, 4.032)
        with patch('tscutter.ffmpeg.subprocess.run', side_effect=runner):
            assert round(f.AudioStartOffset(0), 3) == 4.032
    finally:
        path.unlink()


def test_AudioStartOffset_zero_when_the_lead_in_is_filled():
    """When aresample does fill it, the WAV begins at the container's start."""
    path, f = MakeInputFile()
    try:
        runner = MakeAudioOffsetRunner(27052.586978, 27052.586978, 0.0)
        with patch('tscutter.ffmpeg.subprocess.run', side_effect=runner):
            assert f.AudioStartOffset(0) == 0.0
    finally:
        path.unlink()


def test_AudioStartOffset_zero_when_probe_fails():
    path, f = MakeInputFile()
    try:
        with patch('tscutter.ffmpeg.subprocess.run', return_value=MagicMock(stdout='')):
            assert f.AudioStartOffset(0) == 0.0
    finally:
        path.unlink()


def test_ParseFrameRate():
    assert ParseFrameRate('30000/1001') == pytest.approx(29.97, abs=0.01)
    assert ParseFrameRate('0/0') == 0.0     # ffprobe could not measure the stream
    assert ParseFrameRate(None) == 0.0
    assert ParseFrameRate('') == 0.0
