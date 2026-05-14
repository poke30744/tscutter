import json
from pathlib import Path

class TsFileNotFound(FileNotFoundError): ...
class InvalidTsFormat(RuntimeError): ...

def FormatTimestamp(timestamp):
    seconds = round(timestamp)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = timestamp % 60 
    return f'{hour:02}:{minutes:02}:{seconds:05.02f}'


class PtsMap:
    def __init__(self, path: Path) -> None:
        self.path = path
        with self.path.open() as f:
            self.data = json.load(f)

    def Clips(self) -> list:
        return [ ( float(list(self.data.keys())[i]),  float(list(self.data.keys())[i + 1]) ) for i in range(len(self.data) - 1) ]

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
    
    