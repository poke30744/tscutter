import tempfile, argparse, logging
import logging
from pathlib import Path
from .ffmpeg import InputFile
from .common import FormatTimestamp, CheckExtenralCommand, ProgramNotFound

logger = logging.getLogger('tscutter.audio')

def FormatTimestamp(timestamp):
    seconds = round(timestamp)
    hour = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = timestamp % 60 
    return f'{hour:02}:{minutes:02}:{seconds:05.02f}'

def DetectSilence(inputFile: InputFile, ss=0, to=999999, min_silence_len=800, silence_thresh=-80, quiet=False):
    from pydub import AudioSegment
    from pydub.silence import detect_silence
    try:
        AudioSegment.converter = CheckExtenralCommand('ffmpeg')
    except ProgramNotFound:
        logger.warn('Cannot find ffmpeg in path!')
    with tempfile.TemporaryDirectory(prefix='logoNet_wav_') as tmpWavFolder:
        tmpWavFolder = Path(tmpWavFolder)
        inputFile.ExtractStream(output=tmpWavFolder, ss=ss, to=to, toWav=True, videoTracks=[], audioTracks=[0], quiet=quiet)
        audioFilename = tmpWavFolder / 'audio_0.wav'
        sound = AudioSegment.from_file(audioFilename, channels=1)
        if not quiet:
            logger.info(f'Detect silence (min_silence_len: {min_silence_len},  silence_thresh: {silence_thresh})...')
        periods = detect_silence(audio_segment=sound, min_silence_len=min_silence_len, silence_thresh=silence_thresh, seek_step=10)
        if not quiet:
            logger.info('done!')
        return periods

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Detect silent periods in TS files')
    parser.add_argument('--quiet', '-q', action='store_true', help="don't output to the console")
    parser.add_argument('--input', '-i', required=True, help='input mpegts path')
    parser.add_argument('--length', '-l', type=int, default=800, help='min silence length in ms')
    parser.add_argument('--threshold', '-t', type=int, default=-80, help='silence threshold')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    silencePeriods = DetectSilence(inputFile=InputFile(args.input), min_silence_len=args.length, silence_thresh=args.threshold)
    for period in silencePeriods:
        print(FormatTimestamp(period[0] / 1000), period[1] - period[0])