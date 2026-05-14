import json, shutil, subprocess
from pathlib import Path

class TsFileNotFound(FileNotFoundError): ...
class InvalidTsFormat(RuntimeError): ...
class EncodingError(RuntimeError): ...

def FormatTimestamp(timestamp):
    seconds = round(timestamp)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = timestamp % 60 
    return f'{hour:02}:{minutes:02}:{seconds:05.02f}'

def ClipToFilename(clip):
    return '{:08.3f}-{:08.3f}.ts'.format(float(clip[0]), float(clip[1]))

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
    
    def SplitVideo(self, videoPath: Path, outputFolder: Path, progress=None):
        if outputFolder.exists():
            shutil.rmtree(outputFolder)
        outputFolder.mkdir(parents=True)

        ptsList = list(self.data.keys())
        clips = [(ptsList[i], ptsList[i + 1]) for i in range(len(ptsList) - 1)]
        total_duration = sum(
            self.data[c[1]]['prev_end_pts'] - self.data[c[0]]['next_start_pts']
            for c in clips)
        if progress is not None:
            progress.add_task("split_files", total_duration, "Splitting files", unit="s")
        copied = 0.0
        for clip in clips:
            ss = self.data[clip[0]]['next_start_pts']
            to = self.data[clip[1]]['prev_end_pts']
            outputPath = outputFolder / ClipToFilename(clip)
            subprocess.run([
                'ffmpeg', '-hide_banner', '-y',
                '-i', str(videoPath),
                '-ss', str(ss), '-to', str(to),
                '-c', 'copy', '-map', '0', '-ignore_unknown', '-copy_unknown',
                str(outputPath)
            ], check=True, capture_output=True)
            copied += to - ss
            if progress is not None:
                progress.update("split_files", copied)
        if progress is not None:
            progress.done("split_files")
    