from functools import cache
import json
import shutil, subprocess, tempfile
from pathlib import Path
from dataclasses import dataclass
from ._progress import Progress
import numpy as np
from PIL import Image
import ffmpeg
from .common import TsFileNotFound, InvalidTsFormat
from .service import ResolveServicePids, ServicePids

@dataclass
class VideoInfo:
    duration: float 
    width: int
    height: int
    fps: float
    sar: tuple[int, int]
    dar: tuple[int, int]
    soundTracks: int
    serviceId: int

class InputFile:
    def __init__(self, path, serviceId: int | None = None) -> None:
        self.ffmpeg = shutil.which('ffmpeg')
        self.ffprobe = shutil.which('ffprobe')
        if self.ffmpeg is None:
            raise RuntimeError("ffmpeg not found in PATH — install ffmpeg or add it to PATH")
        if self.ffprobe is None:
            raise RuntimeError("ffprobe not found in PATH — install ffmpeg or add it to PATH")
        self.path = Path(path)
        self.serviceId = serviceId
        if not self.path.is_file():
            raise TsFileNotFound(f'"{self.path.name}" not found!')

    @cache
    def ServicePids(self) -> ServicePids | None:
        """Elementary-stream PIDs of the pinned service, or None when unpinned."""
        if self.serviceId is None:
            return None
        return ResolveServicePids(self.path, self.serviceId, ffprobe=self.ffprobe)

    def MapSpec(self, kind: str, index: int) -> str:
        """ffmpeg stream specifier, by PID when a service is pinned, else by index."""
        pids = self.ServicePids()
        if pids is not None and index == 0:
            spec = pids.MapSpec(kind)
            if spec is not None:
                return spec
        return f'0:{kind}:{index}'

    def ServiceMapArgs(self, kind: str, index: int) -> list[str]:
        """`-map` arguments pinning a stream by PID, or nothing when unpinned.

        Callers that pass no `-map` at all today keep ffmpeg's own stream choice,
        so they must stay untouched unless a service is actually pinned.
        """
        if self.ServicePids() is None:
            return []
        return ['-map', self.MapSpec(kind, index)]

    def SelectStreams(self, streams: list[dict], codecType: str) -> list[dict]:
        """Streams of the given codec type, restricted to the pinned service."""
        selected = [s for s in streams if s.get('codec_type') == codecType]
        pids = self.ServicePids()
        if pids is not None:
            selected = [s for s in selected if int(s.get('id', '0x0'), 16) in pids.allPids]
        return selected

    @cache
    def GetInfo(self) -> VideoInfo:
        try:
            probeInfo = ffmpeg.probe(str(self.path), cmd=self.ffprobe, show_programs=None)
        except (ffmpeg.Error, json.JSONDecodeError, KeyError):
            raise InvalidTsFormat(f'"{self.path.name}" is invalid!')

        video_stream = self.SelectStreams(probeInfo['streams'], 'video')[0]
        audio_streams = self.SelectStreams(probeInfo['streams'], 'audio')

        # Duration: stream level (TS) or format level (MKV)
        duration = float(video_stream.get('duration') or probeInfo['format']['duration'])
        # MKV has no programs; fall back to 0
        programs = probeInfo.get('programs', [])
        serviceId = next((p['program_id'] for p in programs if p['nb_streams'] > 0), 0)

        videoInfo = VideoInfo(
            duration = duration,
            width = video_stream['width'],
            height = video_stream['height'],
            fps = eval(video_stream['avg_frame_rate']),
            sar = video_stream['sample_aspect_ratio'].split(':'),
            dar = video_stream['display_aspect_ratio'].split(':'),
            soundTracks = len(audio_streams),
            serviceId = serviceId,
        )
        return videoInfo

    def ExtractStream(self, output=None, ss=0, to=999999, videoTracks=None, audioTracks=None, toWav=False, progress: Progress | None = None):
        output = self.path.with_suffix('') if output is None else Path(output)
        if output.is_dir():
            shutil.rmtree(output)
        output.mkdir(parents=True)

        args = [
                self.ffmpeg, '-hide_banner', '-y',
                '-ss', str(ss), '-to', str(to), '-i', str(self.path),
                ]

        # copy video tracks
        if videoTracks is None:
            videoTracks = [ 0 ]
        for i in videoTracks:
            args += [  '-map', self.MapSpec('v', i), '-c:v', 'copy', output / f'video_{i}.ts' ]

        # copy audio tracks or decode to WAV
        info = self.GetInfo()
        extName = 'wav' if toWav else 'aac'
        if audioTracks is None:
            audioTracks =  list(range(info.soundTracks))
        for i in audioTracks:
            args += [ '-map', self.MapSpec('a', i) ]
            if toWav:
                args += [ '-f', 'wav' ]
            else:
                args += [ '-c:a', 'copy' ]
            args += [ output / f'audio_{i}.{extName}' ]

        pipeObj = subprocess.Popen(args, stderr=subprocess.PIPE, universal_newlines='\r', errors='ignore')
        to = min(to, info.duration)
        total = to - ss
        tid = "extract_streams"
        if progress is not None:
            progress.add_task(tid, total, "Extracting streams", unit="s")
        last_time = 0.0
        for line in pipeObj.stderr:
            if 'time=' in line:
                for item in line.split(' '):
                    if item.startswith('time='):
                        timeFields = item.replace('time=', '').split(':')
                        try:
                            time = float(timeFields[0]) * 3600 + float(timeFields[1]) * 60 + float(timeFields[2])
                        except ValueError:
                            continue
                        if progress is not None:
                            progress.update(tid, time)
                        last_time = time
        if progress is not None:
            progress.update(tid, total)
            progress.done(tid)
        pipeObj.wait()

    def ExtractFrameDiffs(self, ss, to, fps='2/1') -> list[dict]:
        """Extract frames and compute histogram differences between consecutive frames.
        Uses native source frames (no fps filter). Returns list of {ptsTime, histDiff}."""
        import glob, numpy as np, re
        from PIL import Image

        with tempfile.TemporaryDirectory(prefix='ExtractFrameDiffs_') as tmpFolder:
            args = [
                self.ffmpeg, '-hide_banner',
                '-copyts', '-ss', str(ss), '-to', str(to),
                '-i', str(self.path),
                *self.ServiceMapArgs('v', 0),
                '-vf', 'showinfo',
                '-vsync', '0',
                f'{tmpFolder}/out%08d.bmp',
            ]
            result = subprocess.run(args, capture_output=True, text=True)
            if result.returncode != 0:
                return []
            bmp_files = sorted(glob.glob(f'{tmpFolder}/out*.bmp'))
            if len(bmp_files) < 2:
                return []

            # Parse real PTS from showinfo stderr (absolute source PTS)
            pts_list = []
            for line in result.stderr.split('\n'):
                m = re.search(r'pts_time:(\S+)', line)
                if m:
                    pts_list.append(float(m.group(1)))
            if len(pts_list) != len(bmp_files):
                return []

            diffs = []
            prev_img = np.array(Image.open(bmp_files[0]).convert('L'))
            for i in range(1, len(bmp_files)):
                cur_img = np.array(Image.open(bmp_files[i]).convert('L'))
                ha, _ = np.histogram(prev_img, bins=64, range=(0, 256))
                hb, _ = np.histogram(cur_img, bins=64, range=(0, 256))
                ha, hb = ha.astype(np.float64), hb.astype(np.float64)
                ha /= ha.sum(); hb /= hb.sum()
                diff = np.sum((ha - hb) ** 2 / (ha + hb + 1e-10))
                diffs.append({'ptsTime': pts_list[i - 1], 'histDiff': float(diff)})
                prev_img = cur_img
            return diffs

