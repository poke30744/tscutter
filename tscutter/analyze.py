import argparse, json
from pathlib import Path
import logging
from tqdm import tqdm
from .audio import DetectSilence
from .common import FormatTimestamp, PtsMap
from .ffmpeg import InputFile

logger = logging.getLogger('tscutter.analyze')

def MergeIntervals(intervals):
    if len(intervals) == 0 or len(intervals) == 1:
        return intervals
    intervals.sort(key=lambda x:x[0])
    result = [intervals[0]]
    for interval in intervals[1:]:
        if interval[0] <= result[-1][1]:
            result[-1][1] = max(result[-1][1], interval[1])
        else:
            result.append(interval)
    return result

def FindSplitPosition(inputFile: InputFile, ss, to, splitPosShift=1):
    # We assume scene change occurs between [ {interval start} - 1 sec, {internval end} + 1 sec ]
    propList = inputFile.ExtractFrameProps(((ss-splitPosShift) if (ss-splitPosShift) > 0 else 0), to+splitPosShift)
    if not propList:
        return None, None, None # ffmpeg error
    
    # sceneChange should be found between [ {interval start}, {internval end} ]
    sceneChange = None
    for prop in propList:
        if ss <= prop['ptsTime'] <= to:
            if sceneChange is None:
                sceneChange = prop
            elif prop['sad'] > sceneChange['sad']:
                sceneChange = prop
    if sceneChange is None:
        return None, None, None # ffmpeg error

    iFramesProps = [ prop for prop in propList if prop['type'] == 'I' ]
    prevEnd, nextStart = None, None
    for prop in iFramesProps:
        if prop['ptsTime'] < sceneChange['ptsTime']:
            prevEnd = prop
        elif prop['ptsTime'] > sceneChange['ptsTime']:
            nextStart = prop
            break
    if prevEnd is None:
        prevEnd = sceneChange
    if nextStart is None:
        nextStart = sceneChange
    return prevEnd, sceneChange, nextStart

def LookingForCutLocations(inputFile: InputFile, intervals, splitPosShift, quiet=True):
    locations = []
    for interval in tqdm(intervals, disable=quiet, desc='Looking for cut position'):
        prevEnd, sceneChange, nextStart = FindSplitPosition(inputFile, interval[0] / 1000, interval[1] / 1000, splitPosShift)
        if prevEnd is not None and sceneChange is not None and nextStart is not None:
            locations.append([prevEnd, sceneChange, nextStart])
    return locations

def GeneratePtsMap(inputFile: InputFile, cutLocations):
    duration = inputFile.GetInfo().duration
    fileSize = inputFile.path.stat().st_size
    ptsmap = {
        0.0: {
            'pts_display': FormatTimestamp(0.0),
            'sad': 0.0,
            'silent_ss': 0.0,
            'silent_to': 0.0,
            'prev_end_pts': 0.0,
            'prev_end_sad': 0.0,
            'prev_end_pos': 0,
            'next_start_pts': 0.0,
            'next_start_sad': 0.0,
            'next_start_pos': 0,
        }
    }
    for prevEnd, sceneChange, nextStart in cutLocations:
        sceneChangePts = round(sceneChange['ptsTime'], 8)
        ptsmap[sceneChangePts] = {
            'pts_display': FormatTimestamp(sceneChangePts),
            'sad': sceneChange['sad'],
            'prev_end_pts': prevEnd['ptsTime'],
            'prev_end_sad': prevEnd['sad'],
            'prev_end_pos': prevEnd['pos'],
            'next_start_pts': nextStart['ptsTime'],
            'next_start_sad': nextStart['sad'],
            'next_start_pos': nextStart['pos'],
        }
    ptsmap[duration] = {
        'pts_display': FormatTimestamp(duration),
        'sad': 0.0,
        'silent_ss': duration,
        'silent_to': duration,
        'prev_end_pts': duration,
        'prev_end_sad': 0.0,
        'prev_end_pos': fileSize,
        'next_start_pts': duration,
        'next_start_sad': duration,
        'next_start_pos': fileSize,
    }

    # to remove dublications
    ptsDedup = { round(pts): pts for pts in ptsmap }
    ptsmapDedup = { pts: ptsmap[pts] for pts in sorted(list(ptsDedup.values())) }

    # to remove corrupted items (previous "next_start_pos" >= "next prev_end_pos")
    ptsKeys = list(ptsmapDedup.keys())
    ptsGoodKeys = [ ptsKeys[0] ]
    for nextKey in ptsKeys[1:]:
        prevKey = ptsGoodKeys[-1]
        if ptsmapDedup[prevKey]['next_start_pos'] < ptsmapDedup[nextKey]['prev_end_pos']:
            ptsGoodKeys.append(nextKey)
    ptsmapDedup = { key: ptsmapDedup[key] for key in sorted(ptsGoodKeys) }

    return ptsmapDedup

def AnalyzeVideo(inputFile: InputFile, indexPath=None, outputFolder=None, minSilenceLen=800, silenceThresh=-80, splitPosShift=1, quiet=False):
    if indexPath is None:
        if outputFolder is None:
            outputFolder = inputFile.path.parent
        else:
            outputFolder = Path(outputFolder)
        indexPath = outputFolder / '_metadata' / (inputFile.path.stem + '.ptsmap')
    indexPath.parent.mkdir(parents=True, exist_ok=True)

    separatorIntervals = DetectSilence(inputFile=inputFile, min_silence_len=minSilenceLen, silence_thresh=silenceThresh, quiet=quiet)
    mergedIntervals = MergeIntervals(separatorIntervals)
    logger.info(f'len(mergedIntervals): {len(mergedIntervals)}')
    cutLocations = LookingForCutLocations(inputFile=inputFile, intervals=mergedIntervals, splitPosShift=splitPosShift, quiet=quiet)
    logger.info(f'len(cutLocations): {len(cutLocations)}')
    ptsMap = GeneratePtsMap(inputFile=inputFile, cutLocations=cutLocations)
    logger.info(f'len(ptsMap): {len(ptsMap)}')

    with indexPath.open('w') as f:
        json.dump(ptsMap, f, indent=True)
    return indexPath

def main():
    parser = argparse.ArgumentParser(description='Python tool to cut TS: split by silence and fine-tune by scene change PTS.')
    parser.add_argument('--quiet', '-q', action='store_true', help="don't output to the console")
    subparsers = parser.add_subparsers(required=True, title='subcommands', dest='command')

    subparser = subparsers.add_parser('analyze', help='generate index file of the given mpegts file')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')
    subparser.add_argument('--output', '-o', help='output index path (.ptsmap)')
    subparser.add_argument('--length', '-l', type=int, default=800, help='minimal silence length in ms')
    subparser.add_argument('--threshold', '-t', type=int, default=-80, help='silence threshold')

    subparser = subparsers.add_parser('split', help='split the mpegts file using the index file generated by "analyze"')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')
    subparser.add_argument('--index', '-x', help='input index path (.ptsmap)')
    subparser.add_argument('--output', '-o', help='output folder')

    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    if args.command == 'analyze':
        AnalyzeVideo(inputFile=InputFile(args.input), indexPath=args.output, minSilenceLen=args.length, silenceThresh=args.threshold, quiet=args.quiet)
    elif args.command == 'split':
        videoPath = Path(args.input)
        ptsPath = Path(args.index) if args.index else videoPath.parent / '_metadata' / (videoPath.stem + '.ptsmap')
        outputFolder = Path(args.output) if args.output is not None else videoPath.with_suffix('')
        PtsMap(ptsPath).SplitVideo(videoPath=videoPath, outputFolder=outputFolder)

if __name__ == "__main__":
    main()