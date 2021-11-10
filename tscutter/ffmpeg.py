import shutil, subprocess, re, tempfile
from pathlib import Path
from tqdm import tqdm
import numpy as np
from PIL import Image
from .common import CheckExtenralCommand, TsFileNotFound, InvalidTsFormat

def GetInfoFromLines(lines, suffix=None):
    duration = 0
    if suffix in ('.mp4', '.mkv'):
        pid = 0
        programs = { 0 : { 'soundTracks' : 0 } }
    else:
        programs = {}
    for line in lines:
        if 'Program ' in line:
            pid = line
            programs[pid] = { 'soundTracks' : 0 }
        elif 'Duration' in line:
            durationFields = line.split(',')[0].replace('Duration:', '').strip().split(':')
            duration = float(durationFields[0]) * 3600 + float(durationFields[1]) * 60  + float(durationFields[2])
        if 'Stream #' in line:
            if 'Video:' in line:
                for item in re.findall(r'\d+x\d+', line):
                    sizeFields = item.split('x')
                    if sizeFields[0] != '0' and sizeFields[1] != '0':
                        programs[pid]['width'], programs[pid]['height'] = int(sizeFields[0]), int(sizeFields[1])
                        break
                for item in line.split(','):
                    if ' fps' in item:
                        programs[pid]['fps'] = float(item.replace(' fps', ''))
                        break
                sar = line.split('SAR ')[1].split(' ')[0].split(':')
                sar = int(sar[0]), int(sar[1])
                dar = line.split('DAR ')[1].split(' ')[0].split(']')[0].split(':')
                dar = int(dar[0]), int(dar[1])
                programs[pid]['sar'] = sar
                programs[pid]['dar'] = dar
            elif 'Audio:' in line and 'Hz,' in line:
                programs[pid]['soundTracks'] += 1
        if 'Press [q] to stop' in line or ' time=' in line:
            break
    for pid in programs:
        if programs[pid]['soundTracks'] > 0:
            return {
                'duration': duration, 
                'width': programs[pid]['width'],
                'height': programs[pid]['height'],
                'fps': programs[pid]['fps'],
                'sar': programs[pid]['sar'],
                'dar': programs[pid]['dar'],
                'soundTracks': programs[pid]['soundTracks']
                }
    return None

def GetInfo(path):
    CheckExtenralCommand('ffmpeg')
    path = Path(path)
    if not path.is_file():
        raise TsFileNotFound(f'"{path.name}" not found!')
    pipeObj = subprocess.Popen(
        [
            'ffmpeg', '-hide_banner',
            # seek 30s to jump over the begining
            # over seeking is safe and will be ignored by ffmpeg
            '-ss', '30', '-i', path
        ], 
        stderr=subprocess.PIPE,
        universal_newlines=True,
        errors='ignore')
    try:
        info = GetInfoFromLines(pipeObj.stderr, path.suffix)
    except IndexError:
        raise InvalidTsFormat(f'"{path.name}" is invalid!')
    pipeObj.wait()
    if info is None:
        raise InvalidTsFormat(f'"{path.name}" is invalid!')
    return info

def ExtractStream(path, output=None, ss=0, to=999999, videoTracks=None, audioTracks=None, toWav=False, quiet=False):
    CheckExtenralCommand('ffmpeg')
    path = Path(path)
    if not path.is_file():
        raise TsFileNotFound(f'"{path.name}" not found!')
    output = path.with_suffix('') if output is None else Path(output)
    if output.is_dir():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    
    info = GetInfo(path)

    args = [
            'ffmpeg', '-hide_banner', '-y',
            '-ss', str(ss), '-to', str(to), '-i', path,
            ]
    
    # copy video tracks
    if videoTracks is None:
        videoTracks = [ 0 ]
    for i in videoTracks:
        args += [  '-map', f'0:v:{i}', '-c:v', 'copy', output / f'video_{i}.ts' ]

    # copy audio tracks or decode to WAV
    extName = 'wav' if toWav else 'aac'
    if audioTracks is None:
        audioTracks =  list(range(info['soundTracks']))
    for i in audioTracks:
        args += [ '-map', f'0:a:{i}' ]
        if toWav:
            # to sync corrputed sound tracks with the actual video length
            args += [ '-af',  'aresample=async=1', '-f', 'wav' ]
        else:
            args += [ '-c:a', 'copy' ]
        args += [ output / f'audio_{i}.{extName}' ]

    pipeObj = subprocess.Popen(args, stderr=subprocess.PIPE, universal_newlines='\r', errors='ignore')
    info = GetInfoFromLines(pipeObj.stderr)
    if info is None:
        raise InvalidTsFormat(f'"{path.name}" is invalid!')
   
    if to > info['duration']:
        to = info['duration']
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
    return output

def ExtractFrameProps(path, ss, to, nosad=False):
    CheckExtenralCommand('ffmpeg')
    path = Path(path)
    if not path.is_file():
        raise TsFileNotFound(f'"{path.name}" not found!')
    with tempfile.TemporaryDirectory(prefix='logoNet_frames_') as tmpLogoFolder:
        args = [
            'ffmpeg', '-hide_banner',
            '-ss', str(ss), '-to', str(to),
            '-i', path,
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
        pipeObj = subprocess.Popen(args, stderr=subprocess.PIPE, universal_newlines='\r', errors='ignore')
        propList = []
        info = GetInfoFromLines(pipeObj.stderr)
        if info is None:
            raise InvalidTsFormat(f'"{path.name}" is invalid!')
        if to > info['duration']:
            to = info['duration']
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
            pipeObj.wait()
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
