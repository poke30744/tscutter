import argparse, json, sys
from pathlib import Path
import logging
from rich.logging import RichHandler
from ._progress import Progress
from .audio import DetectSilence
from .common import FormatTimestamp, PtsMap, TsFileNotFound, InvalidTsFormat
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

def FindSplitPosition(inputFile: InputFile, ss, to, splitPosShift=1, progress=None):
    propList = inputFile.ExtractFrameProps(((ss-splitPosShift) if (ss-splitPosShift) > 0 else 0), to+splitPosShift, progress=progress)
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

def LookingForCutLocations(inputFile: InputFile, intervals, splitPosShift, progress: Progress):
    locations = []
    tid = "cut_position"
    progress.add_task(tid, len(intervals), "Finding cut positions")
    for i, interval in enumerate(intervals):
        prevEnd, sceneChange, nextStart = FindSplitPosition(inputFile, interval[0] / 1000, interval[1] / 1000, splitPosShift, progress=progress)
        if prevEnd is not None and sceneChange is not None and nextStart is not None:
            locations.append([prevEnd, sceneChange, nextStart])
        progress.update(tid, i + 1)
    progress.done(tid)
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

def AnalyzeVideo(inputFile: InputFile, indexPath=None, outputFolder=None, minSilenceLen=800, silenceThresh=-80, splitPosShift=1, progress: Progress | None = None):
    if progress is None:
        progress = Progress()
    if indexPath is None:
        if outputFolder is None:
            outputFolder = inputFile.path.parent
        else:
            outputFolder = Path(outputFolder)
        indexPath = outputFolder / '_metadata' / (inputFile.path.stem + '.ptsmap')
    indexPath.parent.mkdir(parents=True, exist_ok=True)

    separatorIntervals = DetectSilence(inputFile=inputFile, min_silence_len=minSilenceLen, silence_thresh=silenceThresh, progress=progress)
    mergedIntervals = MergeIntervals(separatorIntervals)
    cutLocations = LookingForCutLocations(inputFile=inputFile, intervals=mergedIntervals, splitPosShift=splitPosShift, progress=progress)
    ptsMap = GeneratePtsMap(inputFile=inputFile, cutLocations=cutLocations)

    with indexPath.open('w') as f:
        json.dump(ptsMap, f, indent=True)
    return indexPath

def main():
    parser = argparse.ArgumentParser(description='Python tool to cut TS: split by silence and fine-tune by scene change PTS.')
    parser.add_argument('--quiet', '-q', action='store_true', help='suppress non-error output')
    parser.add_argument('--progress', action='store_true', help='output PROGRESS JSON lines for pipeline orchestration')
    subparsers = parser.add_subparsers(required=True, title='subcommands', dest='command')

    subparser = subparsers.add_parser('analyze', help='generate index file of the given mpegts file')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')
    subparser.add_argument('--output', '-o', help='output index path (.ptsmap)')
    subparser.add_argument('--length', '-l', type=int, default=800, help='minimal silence length in ms')
    subparser.add_argument('--threshold', '-t', type=int, default=-80, help='silence threshold')
    subparser.add_argument('--shift', '-s', type=float, default=1, help='split position shift in seconds')

    subparser = subparsers.add_parser('probe', help='probe TS file and output VideoInfo JSON to stdout')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')

    subparser = subparsers.add_parser('list-clips', help='list all clips from a ptsmap file')
    subparser.add_argument('--index', '-x', required=True, help='input index path (.ptsmap)')

    subparser = subparsers.add_parser('select-clips', help='select candidate long clips from a ptsmap file')
    subparser.add_argument('--index', '-x', required=True, help='input index path (.ptsmap)')
    subparser.add_argument('--min-length', type=float, default=150, help='minimum clip length in seconds')

    args = parser.parse_args()

    if args.quiet:
        log_level = logging.WARNING
    else:
        log_level = logging.INFO
    logging.basicConfig(
        level=log_level, format='%(message)s', datefmt='[%X]',
        handlers=[RichHandler(rich_tracebacks=True)])

    progress = Progress(use_protocol=args.progress)

    if args.command == 'analyze':
        AnalyzeVideo(inputFile=InputFile(args.input), indexPath=Path(args.output) if args.output else None, minSilenceLen=args.length, silenceThresh=args.threshold, splitPosShift=args.shift, progress=progress)
    elif args.command == 'probe':
        try:
            info = InputFile(args.input).GetInfo()
        except TsFileNotFound as e:
            print(f'TsFileNotFound: "{args.input}" not found!', file=sys.stderr)
            sys.exit(1)
        except InvalidTsFormat as e:
            print(f'InvalidTsFormat: "{args.input}" is invalid!', file=sys.stderr)
            sys.exit(2)
        print(json.dumps({
            'duration': info.duration,
            'width': info.width,
            'height': info.height,
            'fps': info.fps,
            'sar': list(info.sar),
            'dar': list(info.dar),
            'soundTracks': info.soundTracks,
            'serviceId': info.serviceId,
        }))
    elif args.command == 'list-clips':
        try:
            ptsMap = PtsMap(Path(args.index))
        except FileNotFoundError:
            print(f'FileNotFoundError: {args.index}', file=sys.stderr)
            sys.exit(1)
        except (json.JSONDecodeError, KeyError):
            print(f'InvalidIndexFormat: {args.index}', file=sys.stderr)
            sys.exit(2)
        print(json.dumps(ptsMap.Clips()))
    elif args.command == 'select-clips':
        try:
            ptsMap = PtsMap(Path(args.index))
        except FileNotFoundError:
            print(f'FileNotFoundError: {args.index}', file=sys.stderr)
            sys.exit(1)
        except (json.JSONDecodeError, KeyError):
            print(f'InvalidIndexFormat: {args.index}', file=sys.stderr)
            sys.exit(2)
        selectedClips, _ = ptsMap.SelectClips(lengthLimit=args.min_length)
        print(json.dumps(selectedClips))

if __name__ == "__main__":
    main()