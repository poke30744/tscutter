import sys, subprocess, os, json, shutil
from pathlib import Path
from tqdm import tqdm

class TsFileNotFound(FileNotFoundError): ...
class InvalidTsFormat(RuntimeError): ...
class ProgramNotFound(RuntimeError): ...
class EncodingError(RuntimeError): ...

def CheckExtenralCommand(command):
    if sys.platform == 'win32':
        pipeObj = subprocess.Popen(f'cmd /c where {command}', stdout=subprocess.PIPE)
    else:
        pipeObj = subprocess.Popen(f'which {command}', stdout=subprocess.PIPE, shell=True)
    pipeObj.wait()
    path = pipeObj.stdout.read().decode().split('\r\n')[0]
    if os.path.exists(path):
        return path
    else:
        raise ProgramNotFound(f'{command} not found in $PATH!')

def FormatTimestamp(timestamp):
    seconds = round(timestamp)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = timestamp % 60 
    return f'{hour:02}:{minutes:02}:{seconds:05.02f}'

def ClipToFilename(clip):
    return '{:08.3f}-{:08.3f}.ts'.format(float(clip[0]), float(clip[1]))

def CopyPart(src, dest, start, end, mode='wb', pbar=None, bufsize=1024*1024):
    with open(src, 'rb') as f1:
        f1.seek(start)
        with open(dest, mode) as f2:
            length = end - start
            while length:
                chunk = min(bufsize, length)
                data = f1.read(chunk)
                f2.write(data)
                length -= chunk
                if pbar is not None:
                    pbar.update(chunk)

def CopyPartPipe(src, pipe, start, end,  pbar=None, bufsize=1024*1024):
    try:
        with open(src, 'rb') as f1:
            f1.seek(start)
            length = end - start
            while length:
                chunk = min(bufsize, length)
                data = f1.read(chunk)
                pipe.write(data)
                length -= chunk
                if pbar is not None:
                    pbar.update(chunk)
    except ValueError:
        # pipe is closed by the other side
        pass

class PtsMap:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.path.open() as f:
            self.data = json.load(f)

    def Clips(self) -> list:
        return [ ( float(list(self.data.keys())[i]),  float(list(self.data.keys())[i + 1]) ) for i in range(len(self.data) - 1) ]

    def Duration(self) -> float:
        ptsEnd = list(self.data.keys())[-1]
        return self.data[ptsEnd]['prev_end_pts']
    
    def Length(self) -> int:
        ptsEnd = list(self.data.keys())[-1]
        return self.data[ptsEnd]['prev_end_pos']

    def SelectClips(self, lengthLimit=150) -> tuple:
        clips = self.Clips()
        videoLen = clips[-1][1]
        selectedClips = []
        selectedLen = 0
        for clip in reversed(sorted(clips, key=lambda clip: clip[1] - clip[0])):
            clipLen = clip[1] - clip[0]
            if clipLen < lengthLimit:
                break
            if selectedLen > videoLen / 2:
                break
            selectedClips.append(clip)
            selectedLen += clipLen
        return selectedClips, selectedLen
    
    def SplitVideo(self, videoPath: Path, outputFolder: Path, quiet=False):
        if outputFolder.exists():
            shutil.rmtree(outputFolder)
        outputFolder.mkdir(parents=True)

        ptsList = list(self.data.keys())
        clips = [ (ptsList[i], ptsList[i + 1]) for i in range(len(ptsList) - 1) ]
        for clip in tqdm(clips, desc='splitting files', disable=quiet):
            start, end = self.data[clip[0]]['next_start_pos'], self.data[clip[1]]['prev_end_pos']
            outputPath = outputFolder / ClipToFilename(clip)
            CopyPart(videoPath, outputPath, start, end)
    
    def ExtractClipsPipe(self, inFile: Path, clips: list[tuple[float]], pipe, quiet=True):
        totalSize = 0
        for clip in clips:
            start, end = self.data[str(clip[0])]['next_start_pos'], self.data[str(clip[1])]['prev_end_pos']
            totalSize += end - start
        with tqdm(total=totalSize, unit='B', unit_scale=True, unit_divisor=1024, disable=quiet) as pbar:
            for clip in clips:
                start, end = self.data[str(clip[0])]['next_start_pos'], self.data[str(clip[1])]['prev_end_pos']
                CopyPartPipe(inFile, pipe, start, end, pbar=pbar)
            pipe.close()
    
    def ExtractClipPipe(self, inFile: Path, clip: tuple[float], pipe, quiet=True):
        for pts in [ float(key) for key in self.data.keys() ]:
            if pts <= clip[0]:
                ptsStart = pts
            if pts >= clip[1]:
                ptsEnd = pts
                break
    
        ptsStartPos =  self.data[str(ptsStart)]['next_start_pos']
        ptsEndPos =  self.data[str(ptsEnd)]['prev_end_pos']

        ratio = (ptsEndPos - ptsStartPos) / (ptsEnd - ptsStart)

        start = round(ptsStartPos + (clip[0] - ptsStart) * ratio) // 188 * 188
        totalSize = round((clip[1] - clip[0]) * ratio)
        end = start + totalSize

        with tqdm(total=totalSize, unit='B', unit_scale=True, unit_divisor=1024, disable=quiet) as pbar:
            CopyPartPipe(inFile, pipe, start, end, pbar=pbar)
            pipe.close()
