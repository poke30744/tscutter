import json, logging, shutil, subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger('tscutter.service')

# How much of the file to probe when resolving a service.
PROBE_BYTES = 32 * 1024 * 1024


class ServiceNotFound(RuntimeError): ...


def _hex(pid: int | None) -> str:
    return 'none' if pid is None else f'0x{pid:x}'


@dataclass
class ServicePids:
    programId: int
    pcrPid: int
    video: int | None
    audio: int | None
    subtitle: int | None
    allPids: tuple[int, ...]

    def MapSpec(self, kind: str) -> str | None:
        """ffmpeg stream specifier for this service's stream of the given kind."""
        pid = {'v': self.video, 'a': self.audio, 's': self.subtitle}.get(kind)
        return None if pid is None else f'0:#0x{pid:x}'


def ResolveServicePids(path: Path, serviceId: int, ffprobe: str | None = None) -> ServicePids:
    """Look up the elementary-stream PIDs of one service (program_number).

    Probes from the middle of the file on purpose.  A recording made across a
    BS/CS multi-channel switch can carry two PMT versions with the same service
    id: the demuxer keeps the first one it sees, so probing from the head picks
    up the layout that was valid before the switch, together with the PIDs of a
    service that is no longer part of this one.  Probing from the middle gives
    the PMT that is valid for the bulk of the recording.
    """
    path = Path(path)
    size = path.stat().st_size
    offset = max(0, min(size // 2, size - PROBE_BYTES))
    with path.open('rb') as f:
        f.seek(offset)
        window = f.read(PROBE_BYTES)

    ffprobe = ffprobe or shutil.which('ffprobe')
    if ffprobe is None:
        raise RuntimeError('ffprobe not found in PATH — install ffmpeg or add it to PATH')

    result = subprocess.run(
        [ffprobe, '-v', 'error', '-show_programs', '-of', 'json', '-'],
        input=window, capture_output=True)
    programs = json.loads(result.stdout or b'{}').get('programs', [])
    program = next((p for p in programs if p.get('program_id') == serviceId and p.get('nb_streams')), None)
    if program is None:
        raise ServiceNotFound(f'service {serviceId} not found in "{path.name}"')

    streams = [s for s in program['streams'] if s.get('id')]

    def PidOf(codecType):
        return next((int(s['id'], 16) for s in streams if s.get('codec_type') == codecType), None)

    servicePids = ServicePids(
        programId = program['program_id'],
        pcrPid = program.get('pcr_pid') or 0,
        video = PidOf('video'),
        audio = PidOf('audio'),
        subtitle = PidOf('subtitle'),
        allPids = tuple(int(s['id'], 16) for s in streams),
    )
    logger.info(f'service {servicePids.programId}: video={_hex(servicePids.video)} '
                f'audio={_hex(servicePids.audio)} subtitle={_hex(servicePids.subtitle)} '
                f'pcr={_hex(servicePids.pcrPid)}')
    return servicePids
