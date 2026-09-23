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

def ParseFrameRate(value) -> float:
    """Frame rate as a float.  ffprobe writes "0/0" for a stream it could not
    measure — the SD stream of a BS multi-channel recording often gets that
    treatment — so this returns 0.0 rather than raising."""
    try:
        numerator, denominator = str(value).split('/')
        return float(numerator) / float(denominator) if float(denominator) else 0.0
    except (AttributeError, ValueError):
        return 0.0


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
        self.ffmpeg5 = shutil.which('ffmpeg5')
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

    @cache
    def AudioStartOffset(self, audioTrack: int = 0) -> float:
        """Seconds between the container's start and where this track's WAV starts.

        A WAV decoded by ffmpeg starts at its first sample, so anything timed in
        it is this much earlier than the container's own timeline.  Where that
        first sample lands cannot be read off the stream's start_time: on a
        recording whose head still carries the pre-switch PMT the demuxer cannot
        parse the track and reports the container's start_time for it, and
        whether aresample=async=1 then fills the lead-in with silence — moving
        the WAV back to the container's start — is not decided by that alone.
        Ask the resampler instead: decode a little of the head through the same
        filter chain ExtractStream uses and read the timestamp of the first
        frame it emits.  That timestamp is relative to the mapped stream's own
        start, so adding the stream's offset from the container puts it on the
        container's timeline.
        """
        def probe(args: list[str]) -> str:
            result = subprocess.run([self.ffprobe, '-v', 'error', *args, str(self.path)],
                                    capture_output=True, text=True, errors='replace')
            # A PID that several programs carry is listed once per program, so
            # read the first non-empty row.
            lines = [line for line in result.stdout.splitlines() if line.strip()]
            return lines[0].split(',')[0] if lines else ''

        # Probe the stream ExtractStream would map, not the container's first audio
        # track: with a service pinned those are different streams.
        spec = self.MapSpec('a', audioTrack)
        streamStart = probe(['-select_streams', spec.removeprefix('0:'),
                             '-show_entries', 'stream=start_time', '-of', 'csv=p=0'])
        containerStart = probe(['-show_entries', 'format=start_time', '-of', 'csv=p=0'])
        if not streamStart or not containerStart or 'N/A' in (streamStart, containerStart):
            return 0.0

        result = subprocess.run(
            [self.ffmpeg, '-hide_banner', '-nostdin', '-ss', '0', '-i', str(self.path),
             '-map', spec, '-af', 'aresample=async=1,ashowinfo', '-t', '15',
             '-f', 'null', '-'],
            capture_output=True, text=True, errors='replace')
        firstFrame = next((line.split('pts_time:')[1].split()[0]
                           for line in result.stderr.splitlines()
                           if 'Parsed_ashowinfo' in line and 'pts_time:' in line), None)
        if firstFrame is None:
            return 0.0
        return float(streamStart) - float(containerStart) + float(firstFrame)

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
            # The default probe window (5 MB / 5 s) is too small for a recording
            # that carries two services: ffprobe lists the pinned service's video
            # stream but never parses it, so its width/height come back 0 and its
            # frame rate "0/0".  32 MB was enough for every such file measured.
            probeInfo = ffmpeg.probe(str(self.path), cmd=self.ffprobe, show_programs=None,
                                     probesize='32M', analyzeduration='10M')
        except (ffmpeg.Error, json.JSONDecodeError, KeyError):
            raise InvalidTsFormat(f'"{self.path.name}" is invalid!')

        video_stream = self.SelectStreams(probeInfo['streams'], 'video')[0]
        audio_streams = self.SelectStreams(probeInfo['streams'], 'audio')

        videoInfo = VideoInfo(
            # A stream can come back without a duration of its own; the container's
            # duration is the same figure for a single-service recording.
            duration = float(video_stream.get('duration') or probeInfo['format']['duration']),
            width = video_stream['width'],
            height = video_stream['height'],
            fps = ParseFrameRate(video_stream.get('avg_frame_rate')) or ParseFrameRate(video_stream.get('r_frame_rate')),
            sar = video_stream['sample_aspect_ratio'].split(':'),
            dar = video_stream['display_aspect_ratio'].split(':'),
            soundTracks = len(audio_streams),
            serviceId = next(p['program_id'] for p in probeInfo['programs'] if p['nb_streams'] > 0),
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
                # to sync corrputed sound tracks with the actual video length
                args += [ '-af',  'aresample=async=1', '-f', 'wav' ]
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

    def ExtractFrameProps(self, ss, to, nosad=False, progress=None):
        with tempfile.TemporaryDirectory(prefix='logoNet_frames_') as tmpLogoFolder:
            args = [
                self.ffmpeg5, '-hide_banner',
                '-ss', str(ss), '-to', str(to),
                '-i', str(self.path),
                *self.ServiceMapArgs('v', 0),
                '-filter:v', "select='gte(t,0)',showinfo", '-vsync', '0', '-frame_pts', '1',
            ]
            if nosad:
                args += [
                    '-f', 'null',
                    '-'
                ]
            else:
                args += [
                    f'{tmpLogoFolder}/out%8d.bmp'
            ]
            with subprocess.Popen(args, stderr=subprocess.PIPE, universal_newlines='\r', errors='ignore') as pipeObj:
                propList = []
                to = min(to, self.GetInfo().duration)
                total = to - ss
                tid = "extract_props"
                if progress is not None:
                    progress.add_task(tid, total, "Extracting frame props", unit="s")
                last_pts = 0.0
                for line in pipeObj.stderr:
                    if 'pts_time:' in line:
                        ptsTime = float(line.split('pts_time:')[1].lstrip().split(' ')[0])
                        pos = int(line.split('pos:')[1].lstrip().split(' ')[0])
                        checksum = line.split('checksum:')[1].split(' ')[0]
                        planeChecksum = line.split('plane_checksum:')[1].split('[')[1].split(']')[0].split(' ')
                        meanStrList = line.split('mean:')[1].split('\x08')[0].split(']')[0].lstrip('[').split()
                        stdevStrList = line.split('stdev:')[1].split('\x08')[0].split(']')[0].lstrip('[').split()
                        mean = [ float(i) for i in meanStrList ]
                        stdev = [ float(i) for i in stdevStrList ]
                        isKey = int(line.split(' iskey:')[1].split(' ')[0])
                        frameType = line.split(' type:')[1].split(' ')[0]
                        propList.append({
                            'ptsTime': ptsTime + ss,
                            'pos': pos,
                            'checksum': checksum,
                            'plane_checksum': planeChecksum,
                            'mean': mean,
                            'stdev': stdev,
                            'isKey': isKey,
                            'type': frameType,
                        })
                        last_pts = ptsTime
                        if progress is not None:
                            progress.update(tid, ptsTime)
                if progress is not None:
                    progress.update(tid, total)
                    progress.done(tid)
            if not nosad:
                pathList = sorted(list(Path(tmpLogoFolder).glob('*.bmp')))
                # The clip is corrputed if we cannot extract any image
                if len(pathList) == 0:
                    return []
                originalSize = Image.open(pathList[0]).size
                sadSize = round(originalSize[1] / 8), round(originalSize[0] / 8)
                imageList = [ np.array(Image.open(path).resize(sadSize, Image.NEAREST)) / 255.0 for path in pathList ]
                # The clip is corrputed if we cannot extract the same number of images
                if len(imageList) != len(propList):
                    return []
            else:
                imageList = []
        for i, image in enumerate(imageList):
            if i == 0:
                sad = 0.0
            else:
                sad = np.sum(np.abs(image - imageList[i - 1])) / (sadSize[0] * sadSize[1] * 3)
            propList[i]['sad'] = sad
        for prop in propList[:]:
            if prop['ptsTime'] < ss or prop['ptsTime'] > to:
                propList.remove(prop)
        for prop in propList[:]:
            if prop['pos'] < 0:
                propList.remove(prop)
        return propList
