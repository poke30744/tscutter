from functools import cache
import json
import shutil, subprocess, tempfile
from pathlib import Path
from dataclasses import dataclass
from tqdm import tqdm
import numpy as np
from PIL import Image
import jsonpath_ng.ext as jp
from .common import CheckExtenralCommand, TsFileNotFound, InvalidTsFormat

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
        self.ffmpeg = CheckExtenralCommand('ffmpeg')
        self.ffprobe = CheckExtenralCommand('ffprobe')
        self.path = Path(path)
        if not self.path.is_file():
            raise TsFileNotFound(f'"{self.path.name}" not found!')    
    
    @cache
    def GetInfo(self) -> VideoInfo: 
        with subprocess.Popen(f'"{self.ffprobe}" -v quiet -print_format json -show_format -show_streams -show_programs "{self.path}"', stdout=subprocess.PIPE) as pipeObj:
            try:
                probeInfoJson = pipeObj.stdout.read()
                probeInfo = json.loads(probeInfoJson)
            except IndexError:
                raise InvalidTsFormat(f'"{self.path.name}" is invalid!')
            except ValueError:
                raise InvalidTsFormat(f'"{self.path.name}" is invalid!')
            except KeyError:
                raise InvalidTsFormat(f'"{self.path.name}" is invalid!')
        
        videoInfo = VideoInfo(
            duration = float(jp.parse('$.streams[?(@.codec_type=="video")].duration').find(probeInfo)[0].value),
            width = jp.parse('$.streams[?(@.codec_type=="video")].width').find(probeInfo)[0].value,
            height = jp.parse('$.streams[?(@.codec_type=="video")].height').find(probeInfo)[0].value,
            fps = eval(jp.parse('$.streams[?(@.codec_type=="video")].avg_frame_rate').find(probeInfo)[0].value),
            sar = jp.parse('$.streams[?(@.codec_type=="video")].sample_aspect_ratio').find(probeInfo)[0].value.split(':'),
            dar = jp.parse('$.streams[?(@.codec_type=="video")].display_aspect_ratio').find(probeInfo)[0].value.split(':'),
            soundTracks = len(jp.parse('$.streams[?(@.codec_type=="audio")]').find(probeInfo)),
            serviceId = jp.parse('$.programs[?(@.nb_streams>0)].program_id').find(probeInfo)[0].value,
        )        
        return videoInfo

    def ExtractStream(self, output=None, ss=0, to=999999, videoTracks=None, audioTracks=None, toWav=False, quiet=False):
        output = self.path.with_suffix('') if output is None else Path(output)
        if output.is_dir():
            shutil.rmtree(output)
        output.mkdir(parents=True)

        args = [
                self.ffmpeg, '-hide_banner', '-y',
                '-ss', str(ss), '-to', str(to), '-i', self.path,
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
        with tqdm(total=to - ss, unit='secs', disable=quiet) as pbar:
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
                self.ffmpeg, '-hide_banner',
                '-ss', str(ss), '-to', str(to),
                '-i', self.path,
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
                with tqdm(total=to - ss, unit='secs', disable=not nosad) as pbar:
                    pbar.set_description('Extracting props')
                    for line in pipeObj.stderr:
                        if 'pts_time:' in line:
                            ptsTime = float(line.split('pts_time:')[1].lstrip().split(' ')[0])
                            pos = int(line.split('pos:')[1].lstrip().split(' ')[0])
                            checksum = line.split('checksum:')[1].split(' ')[0]
                            planeChecksum = line.split('plane_checksum:')[1].split('[')[1].split(']')[0].split(' ')
                            meanStrList = line.split('mean:')[1].split('\x08')[0].strip('[]').strip().split(' ')
                            stdevStrList = line.split('stdev:')[1].split('\x08')[0].strip('[]').strip().split(' ')
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
