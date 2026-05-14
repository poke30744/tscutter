import shutil, tempfile, logging
from pathlib import Path
from .ffmpeg import InputFile

logger = logging.getLogger('tscutter.audio')

def DetectSilence(inputFile: InputFile, ss=0, to=999999, min_silence_len=800, silence_thresh=-80, progress=None):
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    AudioSegment.converter = shutil.which('ffmpeg')
    if AudioSegment.converter is None:
        logger.warning('Cannot find ffmpeg in path!')
    with tempfile.TemporaryDirectory(prefix='logoNet_wav_') as tmpWavFolder:
        tmpWavFolder = Path(tmpWavFolder)
        inputFile.ExtractStream(output=tmpWavFolder, ss=ss, to=to, toWav=True, videoTracks=[], audioTracks=[0], progress=progress)
        audioFilename = tmpWavFolder / 'audio_0.wav'
        sound = AudioSegment.from_file(audioFilename, channels=1)
        logger.info(f'Detect silence (min_silence_len: {min_silence_len},  silence_thresh: {silence_thresh})')
        periods = detect_silence(audio_segment=sound, min_silence_len=min_silence_len, silence_thresh=silence_thresh, seek_step=10)
        logger.info('Silence detection done')
        return periods

