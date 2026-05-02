from functools import cache
import json
import shutil, subprocess, tempfile
from pathlib import Path
from dataclasses import dataclass
from tqdm import tqdm
import numpy as np
from PIL import Image
import ffmpeg
from .common import TsFileNotFound, InvalidTsFormat

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
    def __init__(self, path) -> None:
        self.ffmpeg = shutil.which('ffmpeg')
        self.ffprobe = shutil.which('ffprobe')
        self.ffmpeg5 = shutil.which('ffmpeg5')
        self.path = Path(path)
        if not self.path.is_file():
            raise TsFileNotFound(f'"{self.path.name}" not found!')
    
    @cache
    def GetInfo(self) -> VideoInfo:
        try:
            probeInfo = ffmpeg.probe(str(self.path), cmd=self.ffprobe, show_programs=None)
        except (ffmpeg.Error, json.JSONDecodeError, KeyError):
            raise InvalidTsFormat(f'"{self.path.name}" is invalid!')

        video_stream = next(s for s in probeInfo['streams'] if s.get('codec_type') == 'video')
        audio_streams = [s for s in probeInfo['streams'] if s.get('codec_type') == 'audio']

        videoInfo = VideoInfo(
            duration = float(video_stream['duration']),
            width = video_stream['width'],
            height = video_stream['height'],
            fps = eval(video_stream['avg_frame_rate']),
            sar = video_stream['sample_aspect_ratio'].split(':'),
            dar = video_stream['display_aspect_ratio'].split(':'),
            soundTracks = len(audio_streams),
            serviceId = next(p['program_id'] for p in probeInfo['programs'] if p['nb_streams'] > 0),
        )
        return videoInfo

    def ExtractStream(self, output=None, ss=0, to=999999, videoTracks=None, audioTracks=None, toWav=False, quiet=False):
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
            args += [  '-map', f'0:v:{i}', '-c:v', 'copy', output / f'video_{i}.ts' ]

        # copy audio tracks or decode to WAV
        info = self.GetInfo()
        extName = 'wav' if toWav else 'aac'
        if audioTracks is None:
            audioTracks =  list(range(info.soundTracks))
        for i in audioTracks:
            args += [ '-map', f'0:a:{i}' ]
            if toWav:
                # to sync corrputed sound tracks with the actual video length
                args += [ '-af',  'aresample=async=1', '-f', 'wav' ]
            else:
                args += [ '-c:a', 'copy' ]
            args += [ output / f'audio_{i}.{extName}' ]

        pipeObj = subprocess.Popen(args, stderr=subprocess.PIPE, universal_newlines='\r', errors='ignore')
        to = min(to, info.duration)
        with tqdm(total=to - ss, unit='secs') as pbar:
            pbar.set_description('Extracting streams')
            for line in pipeObj.stderr:
                if 'time=' in line:
                    for item in line.split(' '):
                        if item.startswith('time='):
                            timeFields = item.replace('time=', '').split(':')
                            time = float(timeFields[0]) * 3600 + float(timeFields[1]) * 60  + float(timeFields[2])
                            pbar.update(time - pbar.n)
            pbar.update(to - ss - pbar.n)
        pipeObj.wait()

    def ExtractFrameProps(self, ss, to, nosad=False):
        with tempfile.TemporaryDirectory(prefix='logoNet_frames_') as tmpLogoFolder:
            args = [
                self.ffmpeg5, '-hide_banner',
                '-ss', str(ss), '-to', str(to),
                '-i', str(self.path),
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
                with tqdm(total=to - ss, unit='secs') as pbar:
                    pbar.set_description('Extracting props')
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
                            pbar.update(ptsTime - pbar.n)
                    pbar.update(to - ss - pbar.n)
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
