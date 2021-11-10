import sys, subprocess, os

class TsFileNotFound(FileNotFoundError): ...
class InvalidTsFormat(RuntimeError): ...
class ProgramNotFound(RuntimeError): ...
class EncodingError(RuntimeError): ...

def CheckExtenralCommand(command):
    if sys.platform == 'win32':
        pipeObj = subprocess.Popen(f'cmd /c where {command}', stdout=subprocess.PIPE)
    else:
        pipeObj = subprocess.Popen(f'which {command}', stdout=subprocess.PIPE)
    pipeObj.wait()
    path = pipeObj.stdout.read().decode().strip('\r\n')
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
