import argparse, json, shutil
from pathlib import Path
from tqdm import tqdm
from tsutils.audio import DetectSilence
from tsutils.common import FormatTimestamp, ClipToFilename, CopyPart
from tsutils.ffmpeg import GetInfo, ExtractFrameProps

def FindSplitPosition(videoPath, ss, to, sceneChangeSad=None):
    propList = ExtractFrameProps(videoPath, ss, to)
    if not propList:
        return None, None, None # ffmpeg error
    if sceneChangeSad is None:
        sceneChangeSad = max([ prop['sad'] for prop in propList ])
    sceneChangeList = [ prop for prop in propList if prop['sad'] == sceneChangeSad ]
    if len(sceneChangeList) == 0 :
        return None, None, None # ffmpeg error
    else:
        sceneChange = sceneChangeList[0]
    iFramesProps = [ prop for prop in propList if prop['type'] == 'I' ]
    prevEnd, nextStart = None, None
    for prop in iFramesProps:
        if prop['ptsTime'] < sceneChange['ptsTime']:
            prevEnd = prop
        elif prop['ptsTime'] > sceneChange['ptsTime']:
            nextStart = prop
            break
    return prevEnd, sceneChange, nextStart

def GeneratePtsMap(videoPath, separatorPeriods, quiet=False):
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
    if float(separatorPeriods[0][0] / 1000) == 0.0:
        ptsmap[0.0]['silent_to'] = separatorPeriods[0][1] / 1000
        del separatorPeriods[0]

    duration = GetInfo(videoPath)['duration']
    fileSize = Path(videoPath).stat().st_size
    for silence in tqdm(separatorPeriods, disable=quiet, desc='Looking for cut position'):
        ss, to = silence[0] / 1000, silence[1] / 1000
        originalSs, originalTo = ss, to
        sad, prevEnd, nextStart = None, None, None
        while sad is None or prevEnd is None or nextStart is None:
            prevEnd, sceneChange, nextStart = FindSplitPosition(videoPath, ss, to, sad)
            sad = sceneChange['sad'] if sceneChange and sceneChange['sad'] > 0.1 else None
            ss -= 0.5
            to += 0.5
            if ss < 0 or duration - to < 1.0 or abs(originalSs - ss) > 5 or abs(originalTo -to) > 5:
                break
        if ss < 0 or duration - to < 1.0 or abs(originalSs - ss) > 5 or abs(originalTo -to) > 5:
            continue
        sceneChangePts = round(sceneChange['ptsTime'], 8)
        ptsmap[sceneChangePts] = {
            'pts_display': FormatTimestamp(sceneChangePts),
            'sad': sceneChange['sad'],
            'silent_ss': silence[0] / 1000,
            'silent_to': silence[1] / 1000,
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

def AnalyzeVideo(videoPath, indexPath=None, minSilenceLen=800, silenceThresh=-80, force=False, quiet=False):
    videoPath = Path(videoPath)
    _ = videoPath.stat()
    if indexPath is None:
        indexPath = videoPath.parent / '_metadata' / (videoPath.stem + '.ptsmap')
        (videoPath.parent / '_metadata').mkdir(parents=True, exist_ok=True)

    if indexPath.exists() and not force:
        print(f'Skipped analyzing {videoPath.name}')
        return indexPath

    separatorPeriods = DetectSilence(path=videoPath, min_silence_len=minSilenceLen, silence_thresh=silenceThresh)
    ptsMap = GeneratePtsMap(videoPath=videoPath, separatorPeriods=separatorPeriods, quiet=quiet)

    with open(indexPath, 'w') as f:
        json.dump(ptsMap, f, indent=True)
    return indexPath

def SplitVideo(videoPath, indexPath=None, outputFolder=None, quiet=False):
    videoPath = Path(videoPath)
    indexPath = Path(indexPath) if indexPath else videoPath.parent / '_metadata' / (videoPath.stem + '.ptsmap')
    outputFolder = Path(outputFolder) if outputFolder else videoPath.with_suffix('')
    if outputFolder.exists():
        shutil.rmtree(outputFolder)
    outputFolder.mkdir(parents=True)

    with open(indexPath) as f:
        ptsMap = json.load(f)
    ptsList = list(ptsMap.keys())
    clips = [ (ptsList[i], ptsList[i + 1]) for i in range(len(ptsList) - 1) ]
    for clip in tqdm(clips, desc='splitting files', disable=quiet):
        start, end = ptsMap[clip[0]]['next_start_pos'], ptsMap[clip[1]]['prev_end_pos']
        outputPath = outputFolder / ClipToFilename(clip)
        CopyPart(videoPath, outputPath, start, end)
    return outputFolder

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Python tool to cut TS: split by silence and fine-tune by scene change PTS.')
    parser.add_argument('--quiet', '-q', action='store_true', help="don't output to the console")
    subparsers = parser.add_subparsers(required=True, title='subcommands', dest='command')

    subparser = subparsers.add_parser('analyze', help='generate index file of the given mpegts file')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')
    subparser.add_argument('--output', '-o', help='output index path (.ptsmap)')
    subparser.add_argument('--length', '-l', type=int, default=800, help='minimal silence length in ms')
    subparser.add_argument('--threshold', '-t', type=int, default=-80, help='silence threshold')
    subparser.add_argument('--force', '-f', action='store_true', help='Overwrite the existing index file')

    subparser = subparsers.add_parser('split', help='split the mpegts file using the index file generated by "analyze"')
    subparser.add_argument('--input', '-i', required=True, help='input mpegts path')
    subparser.add_argument('--index', '-x', help='input index path (.ptsmap)')
    subparser.add_argument('--output', '-o', help='output folder')

    args = parser.parse_args()

    if args.command == 'analyze':
        AnalyzeVideo(videoPath=args.input, indexPath=args.output, minSilenceLen=args.length, silenceThresh=args.threshold, quiet=args.quiet)
    elif args.command == 'split':
        SplitVideo(videoPath=args.input, indexPath=args.index, outputFolder=args.output, quiet=args.quiet)